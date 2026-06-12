from __future__ import annotations

import neo4j

import app.config as config

# One driver per bolt URI, so the real + both synth instances can coexist
# (needed for the side-by-side COMPLETE/MASKED compare).
_drivers: dict[str, neo4j.Driver] = {}


def get_driver(uri: str | None = None) -> neo4j.Driver:
    """Return a cached Neo4j driver for *uri* (defaults to the real instance).

    All instances share NEO4J_USER / NEO4J_PASSWORD (same docker-compose auth).
    """
    target = uri or config.NEO4J_URI
    driver = _drivers.get(target)
    if driver is None:
        if not config.NEO4J_PASSWORD:
            raise RuntimeError(
                "NEO4J_PASSWORD is not set. Add it to your .env file."
            )
        driver = neo4j.GraphDatabase.driver(
            target,
            auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
        )
        driver.verify_connectivity()
        _drivers[target] = driver
    return driver


def get_driver_for_dataset(dataset_key: str) -> neo4j.Driver:
    """Return the driver for the dataset's Neo4j instance (per the registry)."""
    ds = config.get_dataset(dataset_key)
    return get_driver(ds["neo4j_uri"])


def is_reachable(uri: str) -> bool:
    """True if a driver to *uri* can be opened and verified, else False.

    Never raises — used to drive the connection-status badge when a synth
    instance may be down.
    """
    try:
        get_driver(uri)
        return True
    except Exception:
        return False


def close_all() -> None:
    """Close every cached driver and reset the cache."""
    for driver in _drivers.values():
        try:
            driver.close()
        except Exception:
            pass
    _drivers.clear()


# Backwards-compatible alias (the old single-driver API).
def close_driver() -> None:
    close_all()
