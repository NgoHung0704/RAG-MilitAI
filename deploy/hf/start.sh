#!/usr/bin/env bash
# Container entrypoint: bring up the three Neo4j instances, wait until each one
# answers on Bolt, then hand over to Streamlit.
#
# Nothing is ingested here — every backend is pre-seeded into the image at build
# time (see Dockerfile), so this is a pure start-up path.
set -uo pipefail

NEO4J_BIN=/opt/neo4j/bin
PW="${NEO4J_PASSWORD:-militai-internal}"
APP_PORT="${PORT:-7860}"

start_one() {
  local name=$1 home=$2
  echo "[boot] starting neo4j:${name}"
  NEO4J_CONF="${home}/conf" "${NEO4J_BIN}/neo4j" console \
    > "${home}/logs/console.log" 2>&1 &
}

wait_bolt() {
  local name=$1 port=$2 tries=${3:-120}
  local i
  for ((i = 1; i <= tries; i++)); do
    if "${NEO4J_BIN}/cypher-shell" -a "bolt://127.0.0.1:${port}" \
         -u neo4j -p "${PW}" --format plain "RETURN 1" >/dev/null 2>&1; then
      echo "[boot] neo4j:${name} ready on bolt ${port} (${i}s)"
      return 0
    fi
    sleep 1
  done
  echo "[boot] WARNING neo4j:${name} did not answer on bolt ${port} within ${tries}s"
  tail -n 30 "/srv/neo4j/${name}/logs/console.log" 2>/dev/null || true
  return 1
}

start_one real           /srv/neo4j/real
start_one synth_complete /srv/neo4j/synth_complete
start_one synth_masked   /srv/neo4j/synth_masked

# The real archive has the largest store, so give it the longest grace period.
wait_bolt real           7687 180
wait_bolt synth_complete 7688 60
wait_bolt synth_masked   7689 60

echo "[boot] starting Streamlit on :${APP_PORT}"
exec streamlit run app/main.py \
  --server.address=0.0.0.0 \
  --server.port="${APP_PORT}" \
  --server.headless=true \
  --server.fileWatcherType=none \
  --browser.gatherUsageStats=false
