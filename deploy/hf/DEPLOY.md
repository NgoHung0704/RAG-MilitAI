# Deploying MilitAI to a Hugging Face Space

The Space runs the *whole* system in one container: Streamlit plus the three
Neo4j instances, all pre-seeded at image build time. Nothing is ingested at
runtime, because Spaces discards disk writes between restarts.

Docker Spaces require a paid plan (Pro covers a personal account).

## Layout

```
deploy/hf/
├── Dockerfile            # multi-stage single-container image
├── start.sh              # boots 3× Neo4j, waits for bolt, execs Streamlit
├── gen-neo4j-home.sh     # per-instance NEO4J_CONF home (conf/data/logs)
├── make-seeds.sh         # local stack  -> seeds/  (dumps + vector store)
├── assemble.sh           # seeds + code -> build/space/  (the Space repo)
├── space-README.md       # becomes the Space README (HF YAML frontmatter)
├── gitattributes         # LFS rules for the Space repo
└── seeds/                # build artifacts — not committed to GitHub
```

## 1. Seed from the local stack

The local `docker compose` stack must be **fully ingested** first — in
particular the real archive (~82 808 Soldier nodes and the `soldiers` Chroma
collection). Check:

```bash
docker exec militai-neo4j cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "MATCH (n:Soldier) RETURN count(n)"
```

Then snapshot it. Each container is stopped for the length of its own dump and
restarted right after:

```bash
bash deploy/hf/make-seeds.sh              # all three + chroma
bash deploy/hf/make-seeds.sh real         # or one dataset at a time
```

## 2. Assemble and check locally

```bash
bash deploy/hf/assemble.sh
docker build -t militai-space build/space
docker run --rm -p 7860:7860 -e DEEPSEEK_API_KEY=sk-... militai-space
```

Open <http://localhost:7860>. This is the same image the Space will build, so a
green run here means the only remaining variables are build time and hardware.

## 3. Push to the Space

Create a Space (SDK: **Docker**, visibility **private** or **protected**), then:

```bash
cd build/space
git init && git lfs install
git remote add origin https://huggingface.co/spaces/<user>/<space>
git add . && git commit -m "MilitAI space"
git push --force origin main
```

`.gitattributes` is committed first by `git add .` in the same commit, so the
CSV, the dumps and the vector store go through LFS. Files over 10 MB pushed
outside LFS are rejected by the Hub.

Re-deploying later is the same three commands: `make-seeds.sh` (only if the
data changed), `assemble.sh`, then commit and push from `build/space`.

## 4. Configure the Space

**Settings → Variables and secrets**:

| Name | Kind | Value |
|---|---|---|
| `DEEPSEEK_API_KEY` | secret | required for RAG answers and NL2Cypher |
| `OPENROUTER_API_KEY` | secret | optional; only the offline eval judge uses it |

The Neo4j password is internal to the container (build arg
`NEO4J_INTERNAL_PASSWORD`, default `militai-internal`). The databases listen on
loopback only and are not reachable from outside, so it is not a shared secret —
but do not reuse your local password there.

## Operating notes

- **Hardware.** CPU Basic (free, 2 vCPU / 16 GB) fits: heaps are 2 GB for the
  real instance and 512 MB for each synthetic one, plus Streamlit.
- **Cold start.** Roughly one to two minutes for the three JVMs. Free hardware
  sleeps when idle — wake the Space before a live demo, or move it to CPU
  Upgrade ($0.03/h) for the day so it never sleeps.
- **Build time.** Expect 15–25 minutes, dominated by the dependency layer and
  the upload of the vector store.
- **Image size.** `TORCH_CPU=1` (default) reinstalls torch from the CPU wheel
  index and drops the `nvidia-*` packages the lockfile's Linux resolution pulls
  in — roughly 3 GB saved. Build with `--build-arg TORCH_CPU=0` to fall back to
  the plain lockfile resolution.
- **Neo4j version.** Dumps are restored by the same version that wrote them
  (`5.23.0`, matching `docker-compose.yml`). If you upgrade one, upgrade both:
  `NEO4J_VERSION` in the Dockerfile and `NEO4J_IMAGE` in `make-seeds.sh`.
