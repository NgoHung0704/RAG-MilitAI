"""
Thin wrapper over `docker compose` so the app can start/inspect the Neo4j
containers from a Streamlit button. Best-effort and defensive: every call is
guarded, so a missing/!running Docker never breaks the app.

Only useful when Streamlit runs on the Docker *host* (e.g. local `streamlit run`).
If the app itself runs inside a container without the Docker socket mounted,
`docker_available()` returns False and the UI falls back to a manual hint.
"""

from __future__ import annotations

import shutil
import subprocess

import app.config as config

# compose service name -> container_name (from docker-compose.yml)
NEO4J_CONTAINERS = {
    "neo4j": "militai-neo4j",
    "neo4j-synth-complete": "militai-neo4j-synth-complete",
    "neo4j-synth-masked": "militai-neo4j-synth-masked",
}
NEO4J_SERVICES = list(NEO4J_CONTAINERS)


def docker_available() -> bool:
    """True only if the docker CLI exists AND the daemon answers."""
    if shutil.which("docker") is None:
        return False
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def compose_up(services: list[str] | None = None, timeout: int = 180) -> tuple[bool, str]:
    """`docker compose up -d <services>` from the project root."""
    services = services or NEO4J_SERVICES
    try:
        r = subprocess.run(
            ["docker", "compose", "up", "-d", *services],
            cwd=str(config.PROJECT_ROOT),
            capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode == 0, (r.stdout + "\n" + r.stderr).strip()
    except Exception as exc:
        return False, str(exc)


def container_health(container: str) -> str:
    """Health status ('healthy'/'starting'/…), or container state, or 'absent'."""
    try:
        r = subprocess.run(
            ["docker", "inspect", "-f",
             "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
             container],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return "absent"
        return r.stdout.strip() or "absent"
    except Exception:
        return "unknown"


def neo4j_health() -> dict[str, str]:
    return {svc: container_health(c) for svc, c in NEO4J_CONTAINERS.items()}
