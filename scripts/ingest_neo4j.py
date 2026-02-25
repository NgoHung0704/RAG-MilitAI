"""
One-shot ingestion script: CSV → Neo4j graph database.

Usage:
    python scripts/ingest_neo4j.py                  # full dataset
    python scripts/ingest_neo4j.py --sample          # 4-row sample (for testing)
    python scripts/ingest_neo4j.py --csv path/to.csv

Requires Neo4j to be running and .env to be configured.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from tqdm import tqdm

import app.config as config
from app.graph.connection import get_driver
from app.graph.schema import setup_schema


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _val(v) -> str | int | float | None:
    """Return None for NaN/empty, otherwise the value as-is."""
    if v is None:
        return None
    try:
        if math.isnan(float(v)) if isinstance(v, (int, float)) else False:
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, float) and math.isnan(v):
        return None
    s = str(v).strip()
    return None if s == "" else s


def _int(v) -> int | None:
    raw = _val(v)
    if raw is None:
        return None
    try:
        return int(float(raw))
    except (ValueError, TypeError):
        return None


def _place_key(lieu, departement, pays) -> tuple[str, str, str]:
    """Composite key for Place MERGE — replace None with empty string."""
    return (
        str(lieu or "").strip(),
        str(departement or "").strip(),
        str(pays or "").strip(),
    )


def _soldier_record(row: pd.Series, idx: int) -> dict:
    """Convert a CSV row to a flat dict suitable for Soldier MERGE."""
    return {
        # Identity
        "nom": _val(row.get("nom")) or "",
        "prenom": _val(row.get("prenom")) or "",
        "surnom": _val(row.get("surnom")),
        "age": _int(row.get("age")),
        "profession": _val(row.get("profession")),
        "taille_metre": _val(row.get("taille_metre")),
        "matricule": _val(row.get("matricule")),
        # Birth fields stored directly on Soldier for fast index lookups
        "naissance_jour": _int(row.get("naissance_jour")),
        "naissance_mois": _int(row.get("naissance_mois")),
        "naissance_annee": _int(row.get("naissance_annee")),
        "naissance_lieu": _val(row.get("naissance_lieu")),
        "naissance_departement": _val(row.get("naissance_departement")),
        "naissance_juridiction": _val(row.get("naissance_juridiction")),
        "naissance_region": _val(row.get("naissance_region")),
        "naissance_pays": _val(row.get("naissance_pays")),
        "naissance_pieve": _val(row.get("naissance_pieve")),
        # Domicile fields
        "domicile_lieu": _val(row.get("domicile_lieu")),
        "domicile_departement": _val(row.get("domicile_departement")),
        "domicile_pays": _val(row.get("domicile_pays")),
        # Death fields
        "deces_jour": _int(row.get("deces_jour")),
        "deces_mois": _int(row.get("deces_mois")),
        "deces_annee": _int(row.get("deces_annee")),
        # Marriage fields
        "mariage_jour": _int(row.get("mariage_jour")),
        "mariage_mois": _int(row.get("mariage_mois")),
        "mariage_annee": _int(row.get("mariage_annee")),
        # Service
        "regiment": _val(row.get("regiment")),
        "compagnie": _val(row.get("compagnie")),
        "bataillon": _val(row.get("bataillon")),
        "grade_final": _val(row.get("grade_final")),
        "grade_1": _val(row.get("grade_1")),
        "grade_2": _val(row.get("grade_2")),
        "grade_3": _val(row.get("grade_3")),
        "enrolement_jour": _int(row.get("enrolement_jour")),
        "enrolement_mois": _int(row.get("enrolement_mois")),
        "enrolement_annee": _int(row.get("enrolement_annee")),
        "renvoi_jour": _int(row.get("renvoi_jour")),
        "renvoi_mois": _int(row.get("renvoi_mois")),
        "renvoi_annee": _int(row.get("renvoi_annee")),
        "desertion": _val(row.get("desertion")),
        "desertion_jour": _int(row.get("desertion_jour")),
        "desertion_mois": _int(row.get("desertion_mois")),
        "desertion_annee": _int(row.get("desertion_annee")),
        # Status
        "sort": _val(row.get("sort")),
        "passe": _val(row.get("passe")),
        "invalide": _val(row.get("invalide")),
        "ne_au_regiment": _val(row.get("ne_au_regiment")),
        "commentaires": _val(row.get("commentaires")),
        # Unique key helper (row index in the full CSV)
        "line_idx": idx,
        # Archive
        "source_image": _val(row.get("source_image")) or "",
    }


# ---------------------------------------------------------------------------
# Ingestion functions
# ---------------------------------------------------------------------------

_MERGE_SOLDIER = """
UNWIND $rows AS r
MERGE (s:Soldier {
    nom: r.nom,
    prenom: r.prenom,
    source_image: r.source_image,
    line_idx: r.line_idx
})
SET s += {
    surnom: r.surnom, age: r.age, profession: r.profession,
    taille_metre: r.taille_metre, matricule: r.matricule,
    naissance_jour: r.naissance_jour, naissance_mois: r.naissance_mois,
    naissance_annee: r.naissance_annee, naissance_lieu: r.naissance_lieu,
    naissance_departement: r.naissance_departement,
    naissance_juridiction: r.naissance_juridiction,
    naissance_region: r.naissance_region, naissance_pays: r.naissance_pays,
    naissance_pieve: r.naissance_pieve,
    domicile_lieu: r.domicile_lieu, domicile_departement: r.domicile_departement,
    domicile_pays: r.domicile_pays,
    deces_jour: r.deces_jour, deces_mois: r.deces_mois, deces_annee: r.deces_annee,
    mariage_jour: r.mariage_jour, mariage_mois: r.mariage_mois, mariage_annee: r.mariage_annee,
    regiment: r.regiment, compagnie: r.compagnie, bataillon: r.bataillon,
    grade_final: r.grade_final, grade_1: r.grade_1, grade_2: r.grade_2, grade_3: r.grade_3,
    enrolement_jour: r.enrolement_jour, enrolement_mois: r.enrolement_mois, enrolement_annee: r.enrolement_annee,
    renvoi_jour: r.renvoi_jour, renvoi_mois: r.renvoi_mois, renvoi_annee: r.renvoi_annee,
    desertion: r.desertion, desertion_jour: r.desertion_jour,
    desertion_mois: r.desertion_mois, desertion_annee: r.desertion_annee,
    sort: r.sort, passe: r.passe, invalide: r.invalide,
    ne_au_regiment: r.ne_au_regiment, commentaires: r.commentaires
}
"""

_MERGE_BIRTH = """
UNWIND $rows AS r
MATCH (s:Soldier {nom: r.nom, prenom: r.prenom, source_image: r.source_image, line_idx: r.line_idx})
MERGE (p:Place {lieu: r.lieu, departement: r.dept, pays: r.pays})
MERGE (s)-[rel:BORN_IN]->(p)
SET rel.jour = r.jour, rel.mois = r.mois, rel.annee = r.annee
"""

_MERGE_DEATH = """
UNWIND $rows AS r
MATCH (s:Soldier {nom: r.nom, prenom: r.prenom, source_image: r.source_image, line_idx: r.line_idx})
MERGE (p:Place {lieu: r.lieu, departement: r.dept, pays: r.pays})
MERGE (s)-[rel:DIED_IN]->(p)
SET rel.jour = r.jour, rel.mois = r.mois, rel.annee = r.annee
"""

_MERGE_DOMICILE = """
UNWIND $rows AS r
MATCH (s:Soldier {nom: r.nom, prenom: r.prenom, source_image: r.source_image, line_idx: r.line_idx})
MERGE (p:Place {lieu: r.lieu, departement: r.dept, pays: r.pays})
MERGE (s)-[:DOMICILED_IN]->(p)
"""

_MERGE_MARRIAGE = """
UNWIND $rows AS r
MATCH (s:Soldier {nom: r.nom, prenom: r.prenom, source_image: r.source_image, line_idx: r.line_idx})
MERGE (p:Place {lieu: r.lieu, departement: r.dept, pays: r.pays})
MERGE (s)-[rel:MARRIED_IN]->(p)
SET rel.jour = r.jour, rel.mois = r.mois, rel.annee = r.annee
"""

_MERGE_REGIMENT = """
UNWIND $rows AS r
MATCH (s:Soldier {nom: r.nom, prenom: r.prenom, source_image: r.source_image, line_idx: r.line_idx})
MERGE (reg:Regiment {nom: r.regiment})
MERGE (s)-[rel:SERVED_IN]->(reg)
SET rel.matricule = r.matricule, rel.enrolement_annee = r.enrolement_annee
"""

_MERGE_DESERTION = """
UNWIND $rows AS r
MATCH (s:Soldier {nom: r.nom, prenom: r.prenom, source_image: r.source_image, line_idx: r.line_idx})
MERGE (reg:Regiment {nom: r.regiment})
MERGE (s)-[rel:DESERTED_FROM]->(reg)
SET rel.jour = r.jour, rel.mois = r.mois, rel.annee = r.annee
"""

_MERGE_DISCHARGE = """
UNWIND $rows AS r
MATCH (s:Soldier {nom: r.nom, prenom: r.prenom, source_image: r.source_image, line_idx: r.line_idx})
MERGE (reg:Regiment {nom: r.regiment})
MERGE (s)-[rel:DISCHARGED_FROM]->(reg)
SET rel.jour = r.jour, rel.mois = r.mois, rel.annee = r.annee
"""

_MERGE_COMPANY = """
UNWIND $rows AS r
MATCH (s:Soldier {nom: r.nom, prenom: r.prenom, source_image: r.source_image, line_idx: r.line_idx})
MERGE (c:Company {nom: r.compagnie})
MERGE (s)-[:BELONGS_TO]->(c)
"""

_MERGE_RANK = """
UNWIND $rows AS r
MATCH (s:Soldier {nom: r.nom, prenom: r.prenom, source_image: r.source_image, line_idx: r.line_idx})
MERGE (rk:Rank {nom: r.grade})
MERGE (s)-[rel:HELD_RANK]->(rk)
SET rel.order = r.order
"""

_MERGE_PARENT = """
UNWIND $rows AS r
MATCH (s:Soldier {nom: r.nom, prenom: r.prenom, source_image: r.source_image, line_idx: r.line_idx})
CREATE (p:Person {prenom: r.p_prenom, nom: r.p_nom, profession: r.p_profession, role: r.role})
MERGE (s)-[rel:CHILD_OF]->(p)
SET rel.role = r.role
"""

_MERGE_ARCHIVE = """
UNWIND $rows AS r
MATCH (s:Soldier {nom: r.nom, prenom: r.prenom, source_image: r.source_image, line_idx: r.line_idx})
MERGE (a:ArchiveRecord {source_image: r.source_image})
SET a.section = r.section, a.registre = r.registre,
    a.numero_page = r.numero_page,
    a.ark_url = r.ark_url, a.double_page_url = r.double_page_url
MERGE (s)-[:SOURCED_FROM]->(a)
"""


def _ingest_chunk(session, df_chunk: pd.DataFrame, start_idx: int) -> None:
    rows = []
    for i, (_, row) in enumerate(df_chunk.iterrows()):
        rows.append(_soldier_record(row, start_idx + i))

    # 1. Soldiers
    session.run(_MERGE_SOLDIER, rows=rows)

    # 2. Birth places
    birth_rows = []
    for i, (_, row) in enumerate(df_chunk.iterrows()):
        lieu = _val(row.get("naissance_lieu")) or ""
        dept = _val(row.get("naissance_departement")) or ""
        pays = _val(row.get("naissance_pays")) or ""
        if not (lieu or pays):
            continue
        rec = _soldier_record(row, start_idx + i)
        birth_rows.append({
            **_key(rec),
            "lieu": lieu, "dept": dept, "pays": pays,
            "jour": rec["naissance_jour"], "mois": rec["naissance_mois"], "annee": rec["naissance_annee"],
        })
    if birth_rows:
        session.run(_MERGE_BIRTH, rows=birth_rows)

    # 3. Death places
    death_rows = []
    for i, (_, row) in enumerate(df_chunk.iterrows()):
        lieu = _val(row.get("deces_lieu")) or _val(row.get("deces_commune")) or ""
        dept = _val(row.get("deces_departement")) or ""
        pays = _val(row.get("deces_pays")) or ""
        if not (lieu or pays):
            continue
        rec = _soldier_record(row, start_idx + i)
        death_rows.append({
            **_key(rec),
            "lieu": lieu, "dept": dept, "pays": pays,
            "jour": rec["deces_jour"], "mois": rec["deces_mois"], "annee": rec["deces_annee"],
        })
    if death_rows:
        session.run(_MERGE_DEATH, rows=death_rows)

    # 4. Domicile places
    domicile_rows = []
    for i, (_, row) in enumerate(df_chunk.iterrows()):
        lieu = _val(row.get("domicile_lieu")) or ""
        dept = _val(row.get("domicile_departement")) or ""
        pays = _val(row.get("domicile_pays")) or ""
        if not (lieu or pays):
            continue
        rec = _soldier_record(row, start_idx + i)
        domicile_rows.append({**_key(rec), "lieu": lieu, "dept": dept, "pays": pays})
    if domicile_rows:
        session.run(_MERGE_DOMICILE, rows=domicile_rows)

    # 5. Marriage places
    marriage_rows = []
    for i, (_, row) in enumerate(df_chunk.iterrows()):
        lieu = _val(row.get("mariage_lieu")) or ""
        dept = _val(row.get("mariage_departement")) or ""
        pays = _val(row.get("mariage_pays")) or ""
        if not (lieu or pays):
            continue
        rec = _soldier_record(row, start_idx + i)
        marriage_rows.append({
            **_key(rec),
            "lieu": lieu, "dept": dept, "pays": pays,
            "jour": rec["mariage_jour"], "mois": rec["mariage_mois"], "annee": rec["mariage_annee"],
        })
    if marriage_rows:
        session.run(_MERGE_MARRIAGE, rows=marriage_rows)

    # 6. Regiments
    regiment_rows = [
        {**_key(r), "regiment": r["regiment"],
         "matricule": r["matricule"], "enrolement_annee": r["enrolement_annee"]}
        for r in rows if r.get("regiment")
    ]
    if regiment_rows:
        session.run(_MERGE_REGIMENT, rows=regiment_rows)

    # 7. Desertion
    desertion_rows = [
        {**_key(r), "regiment": r["regiment"],
         "jour": r["desertion_jour"], "mois": r["desertion_mois"], "annee": r["desertion_annee"]}
        for r in rows if r.get("regiment") and r.get("desertion")
    ]
    if desertion_rows:
        session.run(_MERGE_DESERTION, rows=desertion_rows)

    # 8. Discharge
    discharge_rows = [
        {**_key(r), "regiment": r["regiment"],
         "jour": r["renvoi_jour"], "mois": r["renvoi_mois"], "annee": r["renvoi_annee"]}
        for r in rows if r.get("regiment") and r.get("renvoi_annee")
    ]
    if discharge_rows:
        session.run(_MERGE_DISCHARGE, rows=discharge_rows)

    # 9. Companies
    company_rows = [
        {**_key(r), "compagnie": r["compagnie"]}
        for r in rows if r.get("compagnie")
    ]
    if company_rows:
        session.run(_MERGE_COMPANY, rows=company_rows)

    # 10. Ranks
    rank_rows = []
    for r in rows:
        for order, grade_key in [("1", "grade_1"), ("2", "grade_2"), ("3", "grade_3"), ("final", "grade_final")]:
            grade = r.get(grade_key)
            if grade:
                rank_rows.append({**_key(r), "grade": grade, "order": order})
    if rank_rows:
        session.run(_MERGE_RANK, rows=rank_rows)

    # 11. Parents
    parent_rows = []
    for i, (_, row) in enumerate(df_chunk.iterrows()):
        rec = _soldier_record(row, start_idx + i)
        # Father
        pere_prenom = _val(row.get("pere_prenom"))
        if pere_prenom:
            parent_rows.append({
                **_key(rec),
                "role": "father",
                "p_prenom": pere_prenom,
                "p_nom": _val(row.get("pere_autre_prenom")),
                "p_profession": _val(row.get("pere_profession")),
            })
        # Mother
        mere_prenom = _val(row.get("mere_prenom"))
        if mere_prenom:
            parent_rows.append({
                **_key(rec),
                "role": "mother",
                "p_prenom": mere_prenom,
                "p_nom": _val(row.get("mere_nom")) or _val(row.get("mere_autre_nom")),
                "p_profession": None,
            })
    if parent_rows:
        session.run(_MERGE_PARENT, rows=parent_rows)

    # 12. Archive records
    archive_rows = []
    for i, (_, row) in enumerate(df_chunk.iterrows()):
        src = _val(row.get("source_image"))
        if not src:
            continue
        rec = _soldier_record(row, start_idx + i)
        archive_rows.append({
            **_key(rec),
            "source_image": src,
            "section": _val(row.get("section")),
            "registre": _val(row.get("registre")),
            "numero_page": _val(row.get("numero_page")),
            "ark_url": _val(row.get("ark_url")),
            "double_page_url": _val(row.get("double_page_url")),
        })
    if archive_rows:
        session.run(_MERGE_ARCHIVE, rows=archive_rows)


def _key(rec: dict) -> dict:
    """Extract Soldier MATCH key fields."""
    return {
        "nom": rec["nom"],
        "prenom": rec["prenom"],
        "source_image": rec["source_image"],
        "line_idx": rec["line_idx"],
    }



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest CSV into Neo4j")
    parser.add_argument("--csv", default=None, help="Path to CSV file")
    parser.add_argument("--sample", action="store_true",
                        help="Use the 4-row sample file for testing")
    parser.add_argument("--chunk-size", type=int, default=5000,
                        help="Rows per transaction batch (default: 5000)")
    args = parser.parse_args()

    csv_path = args.csv or (config.SAMPLE_DATA_PATH if args.sample else config.DATA_PATH)

    print(f"Connecting to Neo4j at {config.NEO4J_URI} …")
    driver = get_driver()

    print("Setting up schema (constraints + indexes) …")
    setup_schema(driver)

    print(f"Reading {csv_path} …")
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=True)
    total = len(df)
    print(f"  {total} rows loaded.")

    chunk_size = args.chunk_size
    n_chunks = math.ceil(total / chunk_size)

    with driver.session() as session:
        for chunk_idx in tqdm(range(n_chunks), desc="Ingesting chunks", unit="chunk"):
            start = chunk_idx * chunk_size
            end = min(start + chunk_size, total)
            chunk = df.iloc[start:end]
            _ingest_chunk(session, chunk, start)

    print(f"\nDone. Ingested {total} records into Neo4j.")
    driver.close()


if __name__ == "__main__":
    main()
