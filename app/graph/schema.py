"""
Creates Neo4j constraints and indexes.
Run once after the database is empty, or idempotently before ingestion.
"""

from __future__ import annotations

import neo4j


def setup_schema(driver: neo4j.Driver) -> None:
    """Create all uniqueness constraints and search indexes."""
    with driver.session() as session:
        _create_constraints(session)
        _create_indexes(session)


def _create_constraints(session: neo4j.Session) -> None:
    constraints = [
        # Place: composite NODE KEY requires Enterprise Edition.
        # Community Edition workaround: use a plain index on lieu + individual
        # uniqueness is enforced by MERGE in the ingestion script.
        # (index created in _create_indexes instead)
        # Regiment deduplicated by name.
        """
        CREATE CONSTRAINT regiment_unique IF NOT EXISTS
        FOR (r:Regiment) REQUIRE r.nom IS UNIQUE
        """,
        # Company deduplicated by name.
        """
        CREATE CONSTRAINT company_unique IF NOT EXISTS
        FOR (c:Company) REQUIRE c.nom IS UNIQUE
        """,
        # Rank deduplicated by name.
        """
        CREATE CONSTRAINT rank_unique IF NOT EXISTS
        FOR (r:Rank) REQUIRE r.nom IS UNIQUE
        """,
        # ArchiveRecord deduplicated by source image filename.
        """
        CREATE CONSTRAINT archive_unique IF NOT EXISTS
        FOR (a:ArchiveRecord) REQUIRE a.source_image IS UNIQUE
        """,
    ]
    for stmt in constraints:
        session.run(stmt)


def _create_indexes(session: neo4j.Session) -> None:
    indexes = [
        # Place composite index for fast MERGE lookups (Community Edition compatible).
        """
        CREATE INDEX place_lieu IF NOT EXISTS
        FOR (p:Place) ON (p.lieu, p.departement, p.pays)
        """,
        # Soldier lookup indexes (frequently queried fields).
        """
        CREATE INDEX soldier_nom IF NOT EXISTS
        FOR (s:Soldier) ON (s.nom)
        """,
        """
        CREATE INDEX soldier_prenom IF NOT EXISTS
        FOR (s:Soldier) ON (s.prenom)
        """,
        """
        CREATE INDEX soldier_naissance_annee IF NOT EXISTS
        FOR (s:Soldier) ON (s.naissance_annee)
        """,
        """
        CREATE INDEX soldier_deces_annee IF NOT EXISTS
        FOR (s:Soldier) ON (s.deces_annee)
        """,
        """
        CREATE INDEX soldier_enrolement_annee IF NOT EXISTS
        FOR (s:Soldier) ON (s.enrolement_annee)
        """,
    ]
    for stmt in indexes:
        session.run(stmt)
