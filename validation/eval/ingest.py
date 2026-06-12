"""
Load a synthetic-corpus CSV into Neo4j under the **fixed target schema**
(Reference Query Catalogue §1) so the live query modes can be evaluated.

Differences from the shipping `scripts/ingest_neo4j.py` (the §1 [FIX]es):
  - **Parent `MERGE`, not `CREATE`** — father keyed on (child nom_norm +
    pere_prenom_norm), mother on (mere_nom_norm + mere_prenom_norm), so siblings
    share parent nodes and graph genealogy works.
  - **Company** is the primary unit (`BELONGS_TO`).
  - **Place.region** populated; **year fields stored as ints** (range/threshold
    queries work).
  - Every Soldier carries its **`rid`** (0-based corpus row) so live query rows
    reconcile back to gold exactly, and `*_norm` shadow props for fold-matching.

Neo4j Community = one database, so conditions are loaded one at a time
(`wipe=True` clears first). Used by the eval runner's --live flow.

CLI:
    python -m validation.eval.ingest --csv validation/corpus/complete.csv --wipe
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from validation.eval.text import norm

YEAR_COLS = ("naissance_annee", "deces_annee", "enrolement_annee", "mariage_annee",
             "renvoi_annee", "desertion_annee")
NORM_COLS = ("nom", "prenom", "pere_prenom", "mere_nom", "mere_prenom",
             "naissance_lieu", "naissance_departement", "naissance_region",
             "compagnie", "grade_final", "regiment", "surnom")


def _int(v):
    try:
        return int(str(v).strip())
    except (ValueError, TypeError):
        return None


def _rows(df):
    """One dict per record with cleaned values, rid, ints, and *_norm shadows."""
    rows = []
    for rid, (_, r) in enumerate(df.iterrows()):
        d = {c: (str(r[c]).strip() if str(r[c]).strip() != "" else None) for c in df.columns}
        d["rid"] = rid
        for c in YEAR_COLS:
            d[f"{c}_i"] = _int(r.get(c))
        for c in NORM_COLS:
            d[f"{c}_norm"] = norm(r.get(c)) or None
        rows.append(d)
    return rows


SCHEMA = [
    "CREATE CONSTRAINT soldier_rid IF NOT EXISTS FOR (s:Soldier) REQUIRE s.rid IS UNIQUE",
    "CREATE INDEX soldier_nom_norm IF NOT EXISTS FOR (s:Soldier) ON (s.nom_norm)",
    "CREATE INDEX soldier_comp IF NOT EXISTS FOR (s:Soldier) ON (s.compagnie_norm)",
    "CREATE INDEX place_lieu IF NOT EXISTS FOR (p:Place) ON (p.lieu)",
    "CREATE INDEX company_nom IF NOT EXISTS FOR (c:Company) ON (c.nom)",
    "CREATE INDEX person_key IF NOT EXISTS FOR (p:Person) ON (p.role, p.nom_norm, p.prenom_norm)",
]

CY_SOLDIER = """
UNWIND $rows AS r
MERGE (s:Soldier {rid: r.rid})
SET s.nom=r.nom, s.prenom=r.prenom, s.surnom=r.surnom,
    s.nom_norm=r.nom_norm, s.prenom_norm=r.prenom_norm, s.surnom_norm=r.surnom_norm,
    s.age=r.age, s.profession=r.profession,
    s.matricule=r.matricule, s.taille_metre=r.taille_metre,
    s.pied=r.pied, s.pouce=r.pouce, s.ligne=r.ligne,
    s.naissance_lieu=r.naissance_lieu, s.naissance_departement=r.naissance_departement,
    s.naissance_region=r.naissance_region, s.naissance_pays=r.naissance_pays,
    s.naissance_pieve=r.naissance_pieve,
    s.naissance_annee=r.naissance_annee_i,
    s.deces_annee=r.deces_annee_i, s.enrolement_annee=r.enrolement_annee_i,
    s.compagnie=r.compagnie, s.compagnie_norm=r.compagnie_norm,
    s.regiment=r.regiment, s.bataillon=r.bataillon,
    s.grade_final=r.grade_final, s.grade_final_norm=r.grade_final_norm,
    s.desertion=r.desertion, s.desertion_annee=r.desertion_annee_i,
    s.pere_prenom=r.pere_prenom, s.mere_nom=r.mere_nom, s.mere_prenom=r.mere_prenom,
    s.condition=$condition
"""

CY_COMPANY = """
UNWIND $rows AS r
WITH r WHERE r.compagnie IS NOT NULL
MATCH (s:Soldier {rid: r.rid})
MERGE (c:Company {nom: r.compagnie})
MERGE (s)-[:BELONGS_TO]->(c)
"""

CY_BORN = """
UNWIND $rows AS r
WITH r WHERE r.naissance_lieu IS NOT NULL OR r.naissance_departement IS NOT NULL
MATCH (s:Soldier {rid: r.rid})
MERGE (p:Place {lieu: coalesce(r.naissance_lieu,''), departement: coalesce(r.naissance_departement,''), pays: coalesce(r.naissance_pays,'')})
SET p.region = r.naissance_region
MERGE (s)-[rel:BORN_IN]->(p)
SET rel.annee = r.naissance_annee_i
"""

CY_DIED = """
UNWIND $rows AS r
WITH r WHERE r.deces_lieu IS NOT NULL OR r.deces_departement IS NOT NULL
MATCH (s:Soldier {rid: r.rid})
MERGE (p:Place {lieu: coalesce(r.deces_lieu,''), departement: coalesce(r.deces_departement,''), pays: coalesce(r.deces_pays,'')})
MERGE (s)-[rel:DIED_IN]->(p)
SET rel.annee = r.deces_annee_i
"""

CY_REGIMENT = """
UNWIND $rows AS r
WITH r WHERE r.regiment IS NOT NULL
MATCH (s:Soldier {rid: r.rid})
MERGE (g:Regiment {nom: r.regiment})
MERGE (s)-[rel:SERVED_IN]->(g)
SET rel.matricule=r.matricule, rel.enrolement_annee=r.enrolement_annee_i
"""

CY_DESERT = """
UNWIND $rows AS r
WITH r WHERE r.desertion = 'oui' AND r.regiment IS NOT NULL
MATCH (s:Soldier {rid: r.rid})
MERGE (g:Regiment {nom: r.regiment})
MERGE (s)-[rel:DESERTED_FROM]->(g)
SET rel.annee=r.desertion_annee_i
"""

CY_RANK = """
UNWIND $rows AS r
WITH r WHERE r.grade_final IS NOT NULL
MATCH (s:Soldier {rid: r.rid})
MERGE (k:Rank {nom: r.grade_final})
MERGE (s)-[rel:HELD_RANK]->(k)
SET rel.order='final'
"""

# Parent MERGE — shared nodes via composite normalised identity (§1 [FIX]).
CY_FATHER = """
UNWIND $rows AS r
WITH r WHERE r.pere_prenom IS NOT NULL
MATCH (s:Soldier {rid: r.rid})
MERGE (p:Person {role:'father', nom_norm:r.nom_norm, prenom_norm:r.pere_prenom_norm})
ON CREATE SET p.nom=r.nom, p.prenom=r.pere_prenom
MERGE (s)-[:CHILD_OF {role:'father'}]->(p)
"""

CY_MOTHER = """
UNWIND $rows AS r
WITH r WHERE r.mere_nom IS NOT NULL AND r.mere_prenom IS NOT NULL
MATCH (s:Soldier {rid: r.rid})
MERGE (p:Person {role:'mother', nom_norm:r.mere_nom_norm, prenom_norm:r.mere_prenom_norm})
ON CREATE SET p.nom=r.mere_nom, p.prenom=r.mere_prenom
MERGE (s)-[:CHILD_OF {role:'mother'}]->(p)
"""

CY_ARCHIVE = """
UNWIND $rows AS r
WITH r WHERE r.ark_url IS NOT NULL OR r.source_image IS NOT NULL
MATCH (s:Soldier {rid: r.rid})
MERGE (a:ArchiveRecord {source_image: coalesce(r.source_image, toString(r.rid))})
SET a.ark_url=r.ark_url, a.double_page_url=r.double_page_url,
    a.section=r.section, a.registre=r.registre, a.numero_page=r.numero_page
MERGE (s)-[:SOURCED_FROM]->(a)
"""

STAGES = [CY_SOLDIER, CY_COMPANY, CY_BORN, CY_DIED, CY_REGIMENT, CY_DESERT,
          CY_RANK, CY_FATHER, CY_MOTHER, CY_ARCHIVE]


def ingest(driver, csv_path: Path, condition: str, wipe: bool = True):
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    rows = _rows(df)
    with driver.session() as s:
        if wipe:
            s.run("MATCH (n) DETACH DELETE n")
        for stmt in SCHEMA:
            s.run(stmt)
        for cy in STAGES:
            s.run(cy, rows=rows, condition=condition)
    return len(rows)


def get_driver(uri: str | None = None):
    from dotenv import load_dotenv
    from neo4j import GraphDatabase
    load_dotenv()
    uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
    auth = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", ""))
    try:  # silence "unknown property key" notifications on sparse fields
        return GraphDatabase.driver(uri, auth=auth, notifications_min_severity="OFF")
    except (TypeError, ValueError):
        return GraphDatabase.driver(uri, auth=auth)


def main():
    ap = argparse.ArgumentParser(description="Ingest a corpus CSV into Neo4j (fixed §1 schema)")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--condition", default="COMPLETE")
    ap.add_argument("--no-wipe", action="store_true")
    args = ap.parse_args()
    drv = get_driver()
    try:
        n = ingest(drv, Path(args.csv), args.condition, wipe=not args.no_wipe)
        with drv.session() as s:
            nodes = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            rels = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        print(f"Ingested {n} records ({args.condition}) -> {nodes} nodes, {rels} rels")
    finally:
        drv.close()


if __name__ == "__main__":
    main()
