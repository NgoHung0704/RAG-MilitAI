#!/usr/bin/env bash
# Generate a self-contained Neo4j "home" (conf + data + logs) so that several
# instances can share one /opt/neo4j installation inside a single container.
#
#   usage: gen-neo4j-home.sh <home-dir> <bolt-port> <heap> <pagecache>
#
# Only settings that exist in Neo4j 5.x are emitted: strict config validation is
# on by default, so an unknown key would stop the server from starting.
set -euo pipefail

home=$1; port=$2; heap=$3; pagecache=$4

mkdir -p "$home/conf" "$home/data" "$home/logs" "$home/import" "$home/run"

cat > "$home/conf/neo4j.conf" <<CONF
server.directories.data=$home/data
server.directories.logs=$home/logs
server.directories.import=$home/import
server.directories.run=$home/run

# Bolt only, loopback only: the databases are never reachable from outside the
# container, so the Space exposes just the Streamlit port.
server.default_listen_address=127.0.0.1
server.bolt.enabled=true
server.bolt.listen_address=127.0.0.1:$port
server.bolt.advertised_address=127.0.0.1:$port
server.http.enabled=false
server.https.enabled=false

server.memory.heap.initial_size=$heap
server.memory.heap.max_size=$heap
server.memory.pagecache.size=$pagecache

dbms.security.auth_enabled=true
db.logs.query.enabled=OFF
CONF
