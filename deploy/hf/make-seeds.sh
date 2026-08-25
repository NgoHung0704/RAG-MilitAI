#!/usr/bin/env bash
# Snapshot the local stack into deploy/hf/seeds/ — the build inputs of the
# Space image.
#
#   deploy/hf/seeds/neo4j/<dataset>/neo4j.dump   offline dump of that instance
#   deploy/hf/seeds/chroma/                      copy of data/chroma_db
#
# `neo4j-admin database dump` is an offline tool, so each container is stopped
# for the duration of its own dump and restarted immediately afterwards. The
# dump runs in a throwaway container that borrows the volumes of the stopped
# one, which keeps this independent of how the volumes happen to be named.
set -euo pipefail

# Git Bash rewrites container-side paths like /dumps into Windows paths before
# docker ever sees them; this switches that translation off.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

cd "$(dirname "$0")/../.."
ROOT=$(pwd)
SEEDS="$ROOT/deploy/hf/seeds"

NEO4J_IMAGE=${NEO4J_IMAGE:-neo4j:5.23.0-community}

# Docker Desktop on Windows needs a native path for -v; Git Bash provides it
# through `pwd -W`.
hostpath() { (cd "$1" && { pwd -W 2>/dev/null || pwd; }); }

# dataset -> container
datasets="real:militai-neo4j
synth_complete:militai-neo4j-synth-complete
synth_masked:militai-neo4j-synth-masked"

dump_one() {
  local ds=$1 container=$2
  local out="$SEEDS/neo4j/$ds"

  rm -rf "$out"; mkdir -p "$out"
  local host_out; host_out=$(hostpath "$out")

  echo "==> $ds: stopping $container"
  docker stop "$container" >/dev/null
  # Never leave a demo container down because a dump failed.
  trap 'docker start "$container" >/dev/null 2>&1 || true' RETURN ERR

  echo "==> $ds: dumping"
  docker run --rm \
    --volumes-from "$container" \
    --user root \
    --entrypoint neo4j-admin \
    -v "${host_out}:/dumps" \
    "$NEO4J_IMAGE" \
    database dump neo4j --to-path=/dumps

  echo "==> $ds: restarting $container"
  docker start "$container" >/dev/null

  ls -lh "$out"
}

for entry in $datasets; do
  ds=${entry%%:*}
  container=${entry##*:}
  if [ $# -gt 0 ] && [ "$1" != "$ds" ]; then continue; fi
  dump_one "$ds" "$container"
done

if [ $# -eq 0 ] || [ "${1:-}" = "chroma" ]; then
  echo "==> chroma: copying data/chroma_db"
  rm -rf "$SEEDS/chroma"; mkdir -p "$SEEDS/chroma"
  cp -r "$ROOT/data/chroma_db/." "$SEEDS/chroma/"
  du -sh "$SEEDS/chroma"
fi

echo
echo "seeds ready:"
du -sh "$SEEDS"/* 2>/dev/null || true
