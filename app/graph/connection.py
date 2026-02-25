from __future__ import annotations

import neo4j

import app.config as config

_driver: neo4j.Driver | None = None


def get_driver() -> neo4j.Driver:
    """Return the cached Neo4j driver, creating it on first call."""
    global _driver
    if _driver is None:
        if not config.NEO4J_PASSWORD:
            raise RuntimeError(
                "NEO4J_PASSWORD is not set. Add it to your .env file."
            )
        _driver = neo4j.GraphDatabase.driver(
            config.NEO4J_URI,
            auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
        )
        _driver.verify_connectivity()
    return _driver


def close_driver() -> None:
    """Close the Neo4j driver and reset the singleton."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
