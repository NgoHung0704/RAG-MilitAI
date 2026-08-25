#!/usr/bin/env bash
# Assemble the Space repository under build/space/ — a self-contained tree that
# can be built locally with `docker build` and pushed to Hugging Face as-is.
#
#   bash deploy/hf/make-seeds.sh     # once, after the local stack is ingested
#   bash deploy/hf/assemble.sh
#   docker build -t militai-space build/space      # optional local check
#
# The Space repo is deliberately a snapshot rather than the GitHub repo itself:
# it carries build inputs (dumps, vector store) that do not belong in source
# control, and leaves out everything the running app never reads.
set -euo pipefail

cd "$(dirname "$0")/../.."
ROOT=$(pwd)
HF="$ROOT/deploy/hf"
OUT="$ROOT/build/space"

[ -d "$HF/seeds/chroma" ] || { echo "missing $HF/seeds/chroma — run make-seeds.sh first"; exit 1; }
for ds in real synth_complete synth_masked; do
  [ -f "$HF/seeds/neo4j/$ds/neo4j.dump" ] \
    || { echo "missing seeds/neo4j/$ds/neo4j.dump — run make-seeds.sh $ds"; exit 1; }
done

echo "==> resetting $OUT"
rm -rf "$OUT"
mkdir -p "$OUT/deploy" "$OUT/data"

echo "==> build files"
cp "$HF/Dockerfile"          "$OUT/Dockerfile"
cp "$HF/space-README.md"     "$OUT/README.md"
cp "$HF/gitattributes"       "$OUT/.gitattributes"
cp "$HF/dockerignore"        "$OUT/.dockerignore"
cp "$HF/start.sh"            "$OUT/deploy/start.sh"
cp "$HF/gen-neo4j-home.sh"   "$OUT/deploy/gen-neo4j-home.sh"

echo "==> project files"
cp "$ROOT/pyproject.toml" "$ROOT/uv.lock" "$ROOT/.python-version" "$ROOT/showcase.yaml" "$OUT/"
cp -r "$ROOT/app" "$ROOT/scripts" "$ROOT/validation" "$OUT/"

# Only the patched CSV is read at runtime (config.DATA_PATH); the unpatched
# 34 MB twin is never opened by the app, so it stays out of the image.
cp "$ROOT/data/full_unified_annotations_patch.csv" "$ROOT/data/sample_of_data.csv" "$OUT/data/"

echo "==> pruning"
find "$OUT" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$OUT" -name '*.pyc' -delete 2>/dev/null || true
# Regenerable eval embedding cache — the Report tab reads results.json, not this.
rm -rf "$OUT/validation/corpus/eval/chroma"

echo "==> seeds"
mkdir -p "$OUT/seeds"
cp -r "$HF/seeds/neo4j"  "$OUT/seeds/neo4j"
cp -r "$HF/seeds/chroma" "$OUT/seeds/chroma"

echo
echo "assembled:"
du -sh "$OUT"/* | sort -h
echo
echo "total: $(du -sh "$OUT" | cut -f1)"
