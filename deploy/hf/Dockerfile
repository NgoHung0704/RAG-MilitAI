# syntax=docker/dockerfile:1.7
#
# MilitAI — single-container image for Hugging Face Spaces.
#
# Spaces gives you exactly one container, so the five services of
# docker-compose.yml collapse into one: three Neo4j instances (loopback-only,
# bolt 7687/7688/7689) plus the Streamlit app, all sharing one Neo4j
# installation via per-instance NEO4J_CONF homes.
#
# Everything is pre-seeded at BUILD time from ./seeds:
#   seeds/neo4j/<dataset>/neo4j.dump  -> loaded into that instance's store
#   seeds/chroma/                     -> the prebuilt vector store
# so the container never ingests at runtime (MILITAI_AUTOINGEST=off) and a
# restart only costs the JVM boot. Disk written at runtime is discarded by
# Spaces anyway, which is exactly why nothing is generated there.

ARG NEO4J_VERSION=5.23.0

# ---------------------------------------------------------------------------
# base — python + JRE + the Neo4j distribution, shared by every stage
# ---------------------------------------------------------------------------
# Pinned to bookworm: trixie ships only OpenJDK 21, and Neo4j 5.23 is best
# tested on 17. Pinning the distro also keeps the Space build reproducible.
FROM python:3.11-slim-bookworm AS base

ARG NEO4J_VERSION
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        openjdk-17-jre-headless \
        libgomp1 \
        curl \
        ca-certificates \
        procps \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "https://dist.neo4j.org/neo4j-community-${NEO4J_VERSION}-unix.tar.gz" \
      -o /tmp/neo4j.tar.gz \
    && mkdir -p /opt/neo4j \
    && tar -xzf /tmp/neo4j.tar.gz -C /opt/neo4j --strip-components=1 \
    && rm /tmp/neo4j.tar.gz \
    && chmod -R a+rX /opt/neo4j

# Spaces runs the container as uid 1000 — create that user before anything is
# copied in, so no recursive chown is ever needed (it would duplicate layers).
RUN useradd --create-home --uid 1000 --shell /bin/bash user

COPY --chown=user deploy/gen-neo4j-home.sh /usr/local/bin/gen-neo4j-home.sh
RUN chmod +x /usr/local/bin/gen-neo4j-home.sh

# ---------------------------------------------------------------------------
# seeded — restore the three database dumps offline, once, at build time
# ---------------------------------------------------------------------------
FROM base AS seeded

ARG NEO4J_INTERNAL_PASSWORD=militai-internal

RUN mkdir -p /srv/neo4j && chown user:user /srv/neo4j
USER user

RUN gen-neo4j-home.sh /srv/neo4j/real           7687 2G   1G \
    && gen-neo4j-home.sh /srv/neo4j/synth_complete 7688 512m 256m \
    && gen-neo4j-home.sh /srv/neo4j/synth_masked   7689 512m 256m

# Each directory holds a single `neo4j.dump` (the default database of that
# instance). The dumps live only in this stage, so they never reach the final
# image — only the restored stores do.
COPY --chown=user seeds/neo4j/ /tmp/dumps/

RUN set -eu; \
    for ds in real synth_complete synth_masked; do \
      home=/srv/neo4j/$ds; \
      echo "restoring $ds"; \
      NEO4J_CONF=$home/conf /opt/neo4j/bin/neo4j-admin database load neo4j \
        --from-path="/tmp/dumps/$ds" --overwrite-destination=true; \
      NEO4J_CONF=$home/conf /opt/neo4j/bin/neo4j-admin dbms set-initial-password \
        "$NEO4J_INTERNAL_PASSWORD"; \
    done

# ---------------------------------------------------------------------------
# final
# ---------------------------------------------------------------------------
FROM base AS final

ARG NEO4J_INTERNAL_PASSWORD=militai-internal
# The linux resolution of uv.lock pulls the CUDA build of torch (~3 GB of
# nvidia-* wheels) which is dead weight on Spaces CPU hardware. Set to 0 to
# fall back to the plain lockfile resolution.
ARG TORCH_CPU=1
ARG TORCH_VERSION=2.12.0

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/home/user/app/.venv \
    HOME=/home/user \
    HF_HOME=/home/user/.cache/huggingface \
    ANONYMIZED_TELEMETRY=False \
    PATH="/home/user/app/.venv/bin:/opt/neo4j/bin:$PATH"

USER user
WORKDIR /home/user/app

# -- python dependencies --------------------------------------------------- #
COPY --chown=user pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/home/user/.cache/uv,uid=1000,gid=1000 \
    set -eu; \
    uv sync --frozen --no-dev; \
    if [ "$TORCH_CPU" = "1" ]; then \
      uv pip install --python "$UV_PROJECT_ENVIRONMENT" --no-cache \
        --index-url https://download.pytorch.org/whl/cpu \
        --extra-index-url https://pypi.org/simple \
        --index-strategy unsafe-best-match \
        --reinstall-package torch "torch==${TORCH_VERSION}"; \
      drop=$(uv pip list --python "$UV_PROJECT_ENVIRONMENT" \
             | awk '/^nvidia-/ || /^triton[[:space:]]/ {print $1}'); \
      if [ -n "$drop" ]; then \
        uv pip uninstall --python "$UV_PROJECT_ENVIRONMENT" $drop; \
      fi; \
    fi

# -- embedding model, baked in so cold start needs no network -------------- #
ARG EMBEDDING_MODEL=all-MiniLM-L6-v2
RUN python -c "from sentence_transformers import SentenceTransformer; \
SentenceTransformer('${EMBEDDING_MODEL}')"

# -- pre-seeded backends --------------------------------------------------- #
COPY --from=seeded --chown=user /srv/neo4j /srv/neo4j
COPY --chown=user seeds/chroma/ /home/user/app/data/chroma_db/

# -- data + application ---------------------------------------------------- #
COPY --chown=user data/ /home/user/app/data/
COPY --chown=user validation/ /home/user/app/validation/
COPY --chown=user showcase.yaml /home/user/app/showcase.yaml
COPY --chown=user scripts/ /home/user/app/scripts/
COPY --chown=user app/ /home/user/app/app/
COPY --chown=user deploy/start.sh /home/user/app/start.sh
# Set the bit here rather than relying on the checkout: git on Windows records
# 644 (core.filemode=false), so the mode in the repo cannot be trusted.
RUN chmod +x /home/user/app/start.sh

ENV MILITAI_AUTOINGEST=off \
    NEO4J_URI=bolt://127.0.0.1:7687 \
    NEO4J_URI_SYNTH_COMPLETE=bolt://127.0.0.1:7688 \
    NEO4J_URI_SYNTH_MASKED=bolt://127.0.0.1:7689 \
    NEO4J_USER=neo4j \
    NEO4J_PASSWORD=${NEO4J_INTERNAL_PASSWORD} \
    CHROMA_PERSIST_DIR=/home/user/app/data/chroma_db \
    DATA_PATH=/home/user/app/data/full_unified_annotations_patch.csv \
    SAMPLE_DATA_PATH=/home/user/app/data/sample_of_data.csv \
    EMBEDDING_MODEL=all-MiniLM-L6-v2 \
    RAG_TOP_K=5 \
    PORT=7860

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7860/_stcore/health', timeout=3)"

CMD ["/home/user/app/start.sh"]
