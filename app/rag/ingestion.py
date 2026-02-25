"""
CSV → ChromaDB ingestion for the RAG pipeline.

Each CSV row is serialised to a human-readable French-language text block,
then embedded and stored in ChromaDB collection "soldiers".
"""

from __future__ import annotations

import math
from pathlib import Path

import chromadb
import pandas as pd
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from tqdm import tqdm


def _v(val) -> str | None:
    """Return None for NaN/empty values, otherwise a stripped string."""
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    s = str(val).strip()
    return s if s else None


def soldier_to_text(row: dict) -> str:
    """
    Convert a CSV row (as a dict) to a human-readable text block.
    Empty fields are omitted gracefully.
    """
    lines: list[str] = []

    # Identity
    nom = _v(row.get("nom"))
    prenom = _v(row.get("prenom"))
    surnom = _v(row.get("surnom"))

    name_parts = " ".join(filter(None, [prenom, nom]))
    if surnom:
        name_parts += f" (dit {surnom})"
    lines.append(f"Soldat : {name_parts}")

    age = _v(row.get("age"))
    if age:
        lines.append(f"Âge : {age}")

    profession = _v(row.get("profession"))
    if profession:
        lines.append(f"Profession : {profession}")

    taille = _v(row.get("taille_metre"))
    if taille:
        lines.append(f"Taille : {taille} m")

    # Birth
    n_annee = _v(row.get("naissance_annee"))
    n_lieu = _v(row.get("naissance_lieu"))
    n_juridiction = _v(row.get("naissance_juridiction"))
    n_departement = _v(row.get("naissance_departement"))
    n_region = _v(row.get("naissance_region"))
    n_pays = _v(row.get("naissance_pays"))
    n_pieve = _v(row.get("naissance_pieve"))

    birth_parts = []
    if n_annee:
        birth_parts.append(f"an {n_annee}")
    if n_lieu:
        birth_parts.append(n_lieu)
    if n_juridiction and n_juridiction != n_lieu:
        birth_parts.append(f"({n_juridiction})")
    if n_departement:
        birth_parts.append(n_departement)
    if n_region:
        birth_parts.append(n_region)
    if n_pieve:
        birth_parts.append(f"pieve {n_pieve}")
    if n_pays:
        birth_parts.append(n_pays)
    if birth_parts:
        lines.append(f"Naissance : {', '.join(birth_parts)}")

    # Domicile
    d_lieu = _v(row.get("domicile_lieu"))
    d_dept = _v(row.get("domicile_departement"))
    d_pays = _v(row.get("domicile_pays"))
    dom_parts = list(filter(None, [d_lieu, d_dept, d_pays]))
    if dom_parts:
        lines.append(f"Domicile : {', '.join(dom_parts)}")

    # Marriage
    m_annee = _v(row.get("mariage_annee"))
    m_mois = _v(row.get("mariage_mois"))
    m_jour = _v(row.get("mariage_jour"))
    m_lieu = _v(row.get("mariage_lieu"))
    m_pays = _v(row.get("mariage_pays"))
    if m_annee or m_lieu:
        date_parts = list(filter(None, [m_jour, m_mois, m_annee]))
        place_parts = list(filter(None, [m_lieu, m_pays]))
        mariage_str = ""
        if date_parts:
            mariage_str += "/".join(date_parts)
        if place_parts:
            mariage_str += (" à " if date_parts else "") + ", ".join(place_parts)
        lines.append(f"Mariage : {mariage_str}")

    # Death
    d_annee = _v(row.get("deces_annee"))
    d_mois = _v(row.get("deces_mois"))
    d_jour = _v(row.get("deces_jour"))
    d_lieu = _v(row.get("deces_lieu")) or _v(row.get("deces_commune"))
    d_dept = _v(row.get("deces_departement"))
    d_pays = _v(row.get("deces_pays"))
    if d_annee or d_lieu:
        date_parts = list(filter(None, [d_jour, d_mois, d_annee]))
        place_parts = list(filter(None, [d_lieu, d_dept, d_pays]))
        deces_str = ""
        if date_parts:
            deces_str += "/".join(date_parts)
        if place_parts:
            deces_str += (" à " if date_parts else "") + ", ".join(place_parts)
        lines.append(f"Décès : {deces_str}")

    # Military service
    regiment = _v(row.get("regiment"))
    compagnie = _v(row.get("compagnie"))
    bataillon = _v(row.get("bataillon"))
    matricule = _v(row.get("matricule"))
    grade_final = _v(row.get("grade_final"))

    if regiment:
        unit_parts = list(filter(None, [regiment, compagnie, bataillon]))
        lines.append(f"Régiment : {' / '.join(unit_parts)}")
    if matricule:
        lines.append(f"Matricule : {matricule}")
    if grade_final:
        lines.append(f"Grade final : {grade_final}")

    for i, key in enumerate(["grade_1", "grade_2", "grade_3"], start=1):
        g = _v(row.get(key))
        if g:
            lines.append(f"Grade {i} : {g}")

    # Enlistment
    e_annee = _v(row.get("enrolement_annee"))
    e_mois = _v(row.get("enrolement_mois"))
    e_jour = _v(row.get("enrolement_jour"))
    if e_annee:
        date_parts = list(filter(None, [e_jour, e_mois, e_annee]))
        lines.append(f"Enrôlement : {'/'.join(date_parts)}")

    # Discharge
    r_annee = _v(row.get("renvoi_annee"))
    r_mois = _v(row.get("renvoi_mois"))
    r_jour = _v(row.get("renvoi_jour"))
    if r_annee:
        date_parts = list(filter(None, [r_jour, r_mois, r_annee]))
        lines.append(f"Renvoi : {'/'.join(date_parts)}")

    # Desertion
    desertion = _v(row.get("desertion"))
    des_annee = _v(row.get("desertion_annee"))
    if desertion or des_annee:
        des_mois = _v(row.get("desertion_mois"))
        des_jour = _v(row.get("desertion_jour"))
        date_parts = list(filter(None, [des_jour, des_mois, des_annee]))
        des_str = "/".join(date_parts) if date_parts else "oui"
        lines.append(f"Désertion : {des_str}")

    # Father
    pere_prenom = _v(row.get("pere_prenom"))
    if pere_prenom:
        pere_profession = _v(row.get("pere_profession"))
        pere_str = pere_prenom
        if pere_profession:
            pere_str += f", {pere_profession}"
        pere_decede = _v(row.get("pere_decede"))
        if pere_decede:
            pere_str += " (décédé)"
        lines.append(f"Père : {pere_str}")

    # Mother
    mere_prenom = _v(row.get("mere_prenom"))
    if mere_prenom:
        mere_nom = _v(row.get("mere_nom"))
        mere_str = " ".join(filter(None, [mere_prenom, mere_nom]))
        mere_decedee = _v(row.get("mere_decedee"))
        if mere_decedee:
            mere_str += " (décédée)"
        lines.append(f"Mère : {mere_str}")

    # Sort / comments
    sort_val = _v(row.get("sort"))
    if sort_val:
        lines.append(f"Sort : {sort_val}")

    commentaires = _v(row.get("commentaires"))
    if commentaires:
        lines.append(f"Commentaires : {commentaires}")

    # Source
    source_image = _v(row.get("source_image"))
    if source_image:
        lines.append(f"Source : {source_image}")

    return "\n".join(lines)


def _build_metadata(row: dict, row_id: str) -> dict:
    """Extract lightweight metadata stored alongside the vector."""
    return {
        "id": row_id,
        "nom": str(_v(row.get("nom")) or ""),
        "prenom": str(_v(row.get("prenom")) or ""),
        "surnom": str(_v(row.get("surnom")) or ""),
        "regiment": str(_v(row.get("regiment")) or ""),
        "naissance_annee": str(_v(row.get("naissance_annee")) or ""),
        "deces_annee": str(_v(row.get("deces_annee")) or ""),
        "source_image": str(_v(row.get("source_image")) or ""),
        "ark_url": str(_v(row.get("ark_url")) or ""),
        "double_page_url": str(_v(row.get("double_page_url")) or ""),
    }


def ingest_csv(
    csv_path: str,
    persist_dir: str,
    model_name: str,
    batch_size: int = 500,
) -> int:
    """
    Read *csv_path*, embed each row, and upsert into ChromaDB.

    Returns the total number of documents stored.
    """
    Path(persist_dir).mkdir(parents=True, exist_ok=True)

    ef = SentenceTransformerEmbeddingFunction(model_name=model_name)
    client = chromadb.PersistentClient(path=persist_dir)
    collection = client.get_or_create_collection(
        name="soldiers",
        embedding_function=ef,
    )

    df = pd.read_csv(csv_path, dtype=str, keep_default_na=True)
    total = len(df)
    print(f"  {total} rows to embed …")

    n_stored = 0
    for batch_start in tqdm(range(0, total, batch_size), desc="Embedding", unit="batch"):
        batch = df.iloc[batch_start : batch_start + batch_size]

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict] = []

        for i, (_, row) in enumerate(batch.iterrows()):
            row_dict = row.to_dict()
            nom = _v(row_dict.get("nom"))
            prenom = _v(row_dict.get("prenom"))

            # Skip entirely empty name rows
            if not nom and not prenom:
                continue

            row_id = f"row_{batch_start + i}"
            text = soldier_to_text(row_dict)
            meta = _build_metadata(row_dict, row_id)

            ids.append(row_id)
            documents.append(text)
            metadatas.append(meta)

        if ids:
            collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
            n_stored += len(ids)

    return n_stored
