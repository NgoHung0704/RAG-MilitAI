"""
MilitAI synthetic validation corpus generator.

Builds a 180-record corpus with planted ground-truth structures, derives a
masked view, computes gold artifacts, and emits the question set.

Outputs (under validation/corpus/):
    complete.csv      all generated fields present (the truth)
    masked.csv        record-level tiered masking -> real-corpus marginals
    gold/*.json       family partition, link map, origin histograms, stature,
                      trajectories, per-question answers, masked-survival map
    questions.jsonl   ~50 FR/EN authored questions
    seed.txt          the RNG seed (regeneration is byte-for-byte)

Run:  python validation/generate.py
See:  specs/MilitAI_Synthetic_Validation_Spec.md
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import pandas as pd

from pools import (
    BG_SURNAMES, FIRST_NAMES, FEMALE_NAMES, MAIDEN_NAMES, SURNOMS, PROFESSIONS,
    GOLD_COMPANIES, BG_COMPANIES, REGIMENTS, BATAILLONS, RANKS,
    DEPARTMENTS, BG_DEPARTMENTS, jurisdiction_for, region_of, pays_of,
)

SEED = 20260611
HERE = Path(__file__).parent
OUT = HERE / "corpus"
GOLD = OUT / "gold"

# Height unit constants (pied du roi).
PIED_CM, POUCE_CM, LIGNE_CM = 32.48, 2.71, 0.226

# Exact real-CSV column order (schema-faithful for the ingest pipeline).
COLUMNS = [
    "source_image", "double_page", "section", "registre", "numero_page",
    "side", "line", "nom", "nom_autre", "prenom", "surnom", "age",
    "profession", "pied", "pouce", "ligne", "taille_metre",
    "domicile_departement", "domicile_lieu", "domicile_pays",
    "naissance_jour", "naissance_mois", "naissance_annee",
    "naissance_departement", "naissance_lieu", "naissance_juridiction",
    "naissance_region", "naissance_pays", "naissance_pieve",
    "mariage_jour", "mariage_mois", "mariage_annee", "mariage_lieu",
    "mariage_departement", "mariage_pays", "deces_jour", "deces_mois",
    "deces_annee", "deces_lieu", "deces_commune", "deces_departement",
    "deces_pays", "pere_decede", "pere_prenom", "pere_autre_prenom",
    "pere_profession", "mere_decedee", "mere_nom", "mere_autre_nom",
    "mere_prenom", "mere_autre_prenom", "page_bms", "regiment", "compagnie",
    "bataillon", "matricule", "grade_final", "grade_1", "grade_2", "grade_3",
    "renvoi_jour", "renvoi_mois", "renvoi_annee", "desertion",
    "desertion_jour", "desertion_mois", "desertion_annee", "enrolement_jour",
    "enrolement_mois", "enrolement_annee", "sort", "passe", "invalide",
    "ne_au_regiment", "commentaires", "double_page_url", "ark_url",
]

# Fields masked to a target marginal in MASKED (§3.1). Near-100% fields
# (nom, prenom, compagnie, section, registre, numero_page) are not masked.
MASK_TARGETS = {
    "surnom": 0.78, "age": 0.13, "profession": 0.04,
    "naissance_annee": 0.21, "naissance_mois": 0.20, "naissance_jour": 0.20,
    "naissance_lieu": 0.77, "naissance_departement": 0.66,
    "naissance_juridiction": 0.68, "naissance_region": 0.11,
    "naissance_pays": 0.74,
    "domicile_lieu": 0.05, "domicile_departement": 0.05,
    "mariage_annee": 0.03, "mariage_lieu": 0.03, "mariage_departement": 0.03,
    "deces_annee": 0.27, "deces_mois": 0.27, "deces_jour": 0.27,
    "pere_prenom": 0.51, "pere_profession": 0.04, "pere_decede": 0.15,
    "mere_nom": 0.42, "mere_prenom": 0.45, "mere_decedee": 0.15,
    "regiment": 0.15, "bataillon": 0.11, "matricule": 0.84, "grade_final": 0.25,
    "enrolement_annee": 0.83, "enrolement_mois": 0.83, "enrolement_jour": 0.83,
    "desertion": 0.15, "invalide": 0.15, "ne_au_regiment": 0.15,
    "ark_url": 0.84, "double_page_url": 0.97,
}

# Ultra-rare / planted-only fields: in MASKED only the Tier-A planted subset
# survives; the rest lose the field (§4: "Tier-A subset keeps death place
# while the rest lose it").
PLANTED_ONLY = {
    "pied", "pouce", "ligne", "taille_metre", "naissance_pieve",
    "deces_lieu", "deces_departement", "desertion_annee",
}

TIER_RANK = {"A": 0, "B": 1, "C": 2}


def rng_for(rid: int) -> random.Random:
    """Deterministic, order-independent RNG stream per record id."""
    return random.Random(SEED * 100000 + rid)


def cm_of(pied: int, pouce: int, ligne: int) -> float:
    return pied * PIED_CM + pouce * POUCE_CM + ligne * LIGNE_CM


def height_units(target_cm: float):
    """Pick pied/pouce/ligne whose metric is closest to target_cm (>=5 pieds)."""
    pied = 5
    rem = target_cm - pied * PIED_CM
    pouce = max(0, min(11, round(rem / POUCE_CM)))
    rem -= pouce * POUCE_CM
    ligne = max(0, min(11, round(rem / LIGNE_CM)))
    return pied, pouce, ligne


def blank_record(rid: int) -> dict:
    r = {c: "" for c in COLUMNS}
    r["_rid"] = rid
    r["_tier"] = "C"
    r["_tags"] = set()
    r["_family"] = ""        # family id for genealogy gold
    r["_role"] = ""          # vertical-link role: son case id / "father:<case>"
    return r


# ---------------------------------------------------------------------------
# Record construction
# ---------------------------------------------------------------------------

def fill_common(r: dict, *, company: str, department: str, commune: str,
                enrol_year: int, age: int, regiment: str = "",
                with_parents: bool = True):
    """Populate the dense COMPLETE fields shared by most records."""
    rid = r["_rid"]
    rng = rng_for(rid)
    birth_year = enrol_year - age

    r["section"] = "1_YC"
    r["registre"] = str(1 + rid % 6)
    r["numero_page"] = str(2 + rid // 4)
    r["double_page"] = ""
    r["age"] = str(age)
    r["profession"] = rng.choice(PROFESSIONS)
    r["surnom"] = rng.choice(SURNOMS)

    # Birth
    r["naissance_jour"] = str(rng.randint(1, 28))
    r["naissance_mois"] = str(rng.randint(1, 12))
    r["naissance_annee"] = str(birth_year)
    r["naissance_departement"] = department
    r["naissance_lieu"] = commune
    r["naissance_juridiction"] = jurisdiction_for(commune, rid)
    r["naissance_pays"] = pays_of(department)

    # Domicile (often same area)
    r["domicile_departement"] = department
    r["domicile_lieu"] = commune

    # Marriage (dense in COMPLETE, consistent with birth; masked to ~3%)
    r["mariage_annee"] = str(birth_year + rng.randint(20, 30))
    r["mariage_lieu"] = commune
    r["mariage_departement"] = department

    # Death (after enrolment)
    death_year = enrol_year + rng.randint(2, 28)
    r["deces_annee"] = str(death_year)
    r["deces_mois"] = str(rng.randint(1, 12))
    r["deces_jour"] = str(rng.randint(1, 28))

    # Parents (patronymic: father's surname == soldier nom; mother maiden name)
    if with_parents:
        r["pere_prenom"] = rng.choice(FIRST_NAMES)
        r["pere_profession"] = rng.choice(PROFESSIONS)
        r["pere_decede"] = "oui" if rng.random() < 0.5 else "non"
        r["mere_nom"] = rng.choice(MAIDEN_NAMES)
        r["mere_prenom"] = rng.choice(FEMALE_NAMES)
        r["mere_decedee"] = "oui" if rng.random() < 0.5 else "non"

    # Military / service — all generated fields dense in COMPLETE; masking
    # (§4) reduces them to the §3.1 marginals. grade_final is rank-weighted
    # toward plain "soldat" (most men held no higher rank).
    r["compagnie"] = company
    r["regiment"] = regiment or rng.choice(REGIMENTS)
    r["bataillon"] = rng.choice(BATAILLONS)
    r["matricule"] = str(1000 + rid)
    r["grade_final"] = "soldat" if rng.random() < 0.6 else rng.choice(RANKS[1:])
    r["enrolement_jour"] = str(rng.randint(1, 28))
    r["enrolement_mois"] = str(rng.randint(1, 12))
    r["enrolement_annee"] = str(enrol_year)
    r["desertion"] = "oui" if rng.random() < 0.18 else "non"
    r["invalide"] = "oui" if rng.random() < 0.18 else "non"
    r["ne_au_regiment"] = "oui" if rng.random() < 0.12 else "non"

    # Provenance URLs
    r["double_page_url"] = f"https://archives.example/dp/{1000 + rid}.jpg"
    r["ark_url"] = f"https://archives.example/ark:/{2000 + rid}/p{rid}"


def set_family(r, *, nom, pere_prenom="", mere_nom="", mere_prenom=""):
    r["nom"] = nom
    if pere_prenom != "":
        r["pere_prenom"] = pere_prenom
    if mere_nom != "":
        r["mere_nom"] = mere_nom
    if mere_prenom != "":
        r["mere_prenom"] = mere_prenom


# ---------------------------------------------------------------------------
# Build the corpus
# ---------------------------------------------------------------------------

def build_records() -> list[dict]:
    records: list[dict] = []
    rid = 0

    def new(**meta) -> dict:
        nonlocal rid
        r = blank_record(rid)
        r["_tier"] = meta.get("tier", "C")
        r["_family"] = meta.get("family", "")
        r["_role"] = meta.get("role", "")
        if meta.get("tags"):
            r["_tags"] = set(meta["tags"])
        records.append(r)
        rid += 1
        return r

    D = DEPARTMENTS

    # Reserved (nom, prenom) keys: background fillers must never reproduce these,
    # so the planted vertical-link, family, homonym and single-record probes stay
    # clean and uniquely identifiable by the reference questions' params.
    blocked_keys = {
        # vertical-link father keys (one true father per son name)
        ("DUPONT", "Pierre"), ("GIRARD", "Mathieu"), ("ROUX", "Nicolas"),
        ("MOREAU", "Jacques"), ("BLANC", "Michel"),
        # planted single-record / hub probes
        ("DUPONT", "Jean"), ("MOREAU", "Pierre"), ("GIRARD", "Louis"),
        ("ROUX", "Antoine"), ("BLANC", "Jacques"), ("FAURE", "André"),
        ("RENARD", "Louis"), ("RENARD", "Mathieu"), ("LEROY", "Guillaume"),
        ("BERNARD", "Louis"), ("CHALET", "Jean"), ("CHALET", "Pierre"),
    }

    # ----- Cie A : concentrated Breton, 9 Finistère / 3 CdN / 3 Morbihan -----
    fin = D["Finistère"]["communes"]
    cdn = D["Côtes-du-Nord"]["communes"]
    mor = D["Morbihan"]["communes"]

    # a0..a2 FAM-CLEAN-1: DUPONT brothers (Finistère/Quimper). Jean DUPONT is the
    # hub probe — a clean-family member AND the VERT-TRUE son (father DUPONT
    # Pierre at gap 30) AND the RQ-MULTI / RQ-PAR-01 anchor.
    for i, by in enumerate((1688, 1690, 1692)):
        r = new(family="FAM-CLEAN-1", tier=("A" if i < 2 else "B"),
                tags={"clean_family"})
        fill_common(r, company=GOLD_COMPANIES["A"], department="Finistère",
                    commune="Quimper", enrol_year=1710, age=1710 - by)
        set_family(r, nom="DUPONT", pere_prenom="Pierre",
                   mere_nom="Le Bras", mere_prenom="Marie")
        r["prenom"] = ["Jean", "Mathieu", "Guillaume"][i]
        if i == 0:  # Jean DUPONT also serves as the VERT-TRUE son
            r["_role"] = "VERT-TRUE"
            r["_tags"].add("vert_son")
    # a3 plain Finistère filler (Brest)
    r = new(tier="A")
    fill_common(r, company=GOLD_COMPANIES["A"], department="Finistère",
                commune="Brest", enrol_year=1710, age=20)
    r["nom"] = "GUEGAN"
    r["prenom"] = "Hervé"
    # a4..a8 Finistère fillers (a4,a5 stature cohort Tier-A)
    for i in range(5):
        r = new(tier=("A" if i < 2 else "C"),
                tags=({"stature"} if i < 5 else set()))
        fill_common(r, company=GOLD_COMPANIES["A"], department="Finistère",
                    commune=fin[i % len(fin)], enrol_year=1708 + (i % 5),
                    age=22 + i)
        r["nom"] = BG_SURNAMES[(rid * 3) % len(BG_SURNAMES)]
        r["prenom"] = FIRST_NAMES[(rid * 5) % len(FIRST_NAMES)]
        r["_tags"].add("stature")
    # a9 VERT-YOUNG son: GIRARD Louis (CdN/Saint-Brieuc), birth 1692, father gap ~17
    r = new(role="VERT-YOUNG", tier="A", tags={"vert_son"})
    fill_common(r, company=GOLD_COMPANIES["A"], department="Côtes-du-Nord",
                commune="Saint-Brieuc", enrol_year=1712, age=20)
    set_family(r, nom="GIRARD", pere_prenom="Mathieu")
    r["prenom"] = "Louis"
    # a10,a11 CdN fillers
    for i in range(2):
        r = new(tier="C")
        fill_common(r, company=GOLD_COMPANIES["A"], department="Côtes-du-Nord",
                    commune=cdn[(i + 1) % len(cdn)], enrol_year=1709 + i, age=24 + i)
        r["nom"] = BG_SURNAMES[(rid * 7) % len(BG_SURNAMES)]
        r["prenom"] = FIRST_NAMES[(rid * 11) % len(FIRST_NAMES)]
    # a12,a13 FAM-CLEAN-2 brothers (Morbihan/Vannes)
    for i, by in enumerate((1689, 1691)):
        r = new(family="FAM-CLEAN-2", tier="B", tags={"clean_family"})
        fill_common(r, company=GOLD_COMPANIES["A"], department="Morbihan",
                    commune="Vannes", enrol_year=1711, age=1711 - by)
        set_family(r, nom="LE GOFF", pere_prenom="Jean",
                   mere_nom="Cariou", mere_prenom="Jeanne")
        r["prenom"] = ["René", "Olivier"][i]
    # a14 Morbihan filler
    r = new(tier="C")
    fill_common(r, company=GOLD_COMPANIES["A"], department="Morbihan",
                commune="Auray", enrol_year=1710, age=27)
    r["nom"] = BG_SURNAMES[(rid * 7) % len(BG_SURNAMES)]
    r["prenom"] = FIRST_NAMES[(rid * 13) % len(FIRST_NAMES)]

    # ----- Cie B : East split, 5 Bas-Rhin / 5 Moselle / 4 Meurthe -----
    bra = D["Bas-Rhin"]["communes"]
    mos = D["Moselle"]["communes"]
    meu = D["Meurthe"]["communes"]
    # b0 VERT-OLD son: ROUX Antoine (Bas-Rhin/Strasbourg), birth 1690, father gap ~52.
    # Also an Alsace stature-cohort member.
    r = new(role="VERT-OLD", tier="A", tags={"vert_son", "stature"})
    fill_common(r, company=GOLD_COMPANIES["B"], department="Bas-Rhin",
                commune="Strasbourg", enrol_year=1712, age=22)
    set_family(r, nom="ROUX", pere_prenom="Nicolas")
    r["prenom"] = "Antoine"
    # b1..b4 Bas-Rhin fillers — the Alsace stature cohort (region mean ~163)
    for i in range(4):
        r = new(tier="C", tags={"stature"})
        fill_common(r, company=GOLD_COMPANIES["B"], department="Bas-Rhin",
                    commune=bra[(i + 1) % len(bra)], enrol_year=1710 + (i % 5),
                    age=23 + i)
        r["nom"] = BG_SURNAMES[(rid * 3) % len(BG_SURNAMES)]
        r["prenom"] = FIRST_NAMES[(rid * 5) % len(FIRST_NAMES)]
    # b5,b6 FAM-CLEAN-3 brothers (Moselle/Metz) — clean family, not stature
    for i, by in enumerate((1690, 1693)):
        r = new(family="FAM-CLEAN-3", tier="A", tags={"clean_family"})
        fill_common(r, company=GOLD_COMPANIES["B"], department="Moselle",
                    commune="Metz", enrol_year=1713, age=1713 - by)
        set_family(r, nom="SCHMITT", pere_prenom="Nicolas",
                   mere_nom="Becker", mere_prenom="Anne")
        r["prenom"] = ["Joseph", "Antoine"][i]
    # b7,b8,b9 Moselle fillers
    for i in range(3):
        r = new(tier="C")
        fill_common(r, company=GOLD_COMPANIES["B"], department="Moselle",
                    commune=mos[(i + 1) % len(mos)], enrol_year=1711 + i, age=24 + i)
        r["nom"] = BG_SURNAMES[(rid * 7) % len(BG_SURNAMES)]
        r["prenom"] = FIRST_NAMES[(rid * 11) % len(FIRST_NAMES)]
    # b10..b13 Meurthe fillers
    for i in range(4):
        r = new(tier="C")
        fill_common(r, company=GOLD_COMPANIES["B"], department="Meurthe",
                    commune=meu[i % len(meu)], enrol_year=1712 + (i % 4), age=25 + i)
        r["nom"] = BG_SURNAMES[(rid * 5) % len(BG_SURNAMES)]
        r["prenom"] = FIRST_NAMES[(rid * 7) % len(FIRST_NAMES)]

    # ----- Cie C : dispersed national, 2 each of 6 departments -----
    c_layout = ["Seine", "Seine", "Rhône", "Rhône", "Gironde", "Gironde",
                "Nord", "Nord", "Isère", "Isère", "Puy-de-Dôme", "Puy-de-Dôme"]
    for i, dep in enumerate(c_layout):
        commune = D[dep]["communes"][i % len(D[dep]["communes"])]
        if i == 0:  # c0 VERT-DECOY son: MOREAU Pierre (Seine/Paris)
            r = new(role="VERT-DECOY", tier="B", tags={"vert_son"})
            fill_common(r, company=GOLD_COMPANIES["C"], department="Seine",
                        commune="Paris", enrol_year=1710, age=20)
            set_family(r, nom="MOREAU", pere_prenom="Jacques")
            r["prenom"] = "Pierre"
        else:
            r = new(tier="C")
            fill_common(r, company=GOLD_COMPANIES["C"], department=dep,
                        commune=commune, enrol_year=1705 + (i % 16), age=22 + (i % 20))
            r["nom"] = BG_SURNAMES[(rid * 3) % len(BG_SURNAMES)]
            r["prenom"] = FIRST_NAMES[(rid * 5) % len(FIRST_NAMES)]

    # ----- Cie D : overlaps A + Paris, 4 Finistère / 3 Morbihan / 5 Seine / 2 Eure -----
    # d0,d1 FAM-CLEAN-4 brothers (Finistère/Brest)
    for i, by in enumerate((1689, 1692)):
        r = new(family="FAM-CLEAN-4", tier="A", tags={"clean_family"})
        fill_common(r, company=GOLD_COMPANIES["D"], department="Finistère",
                    commune="Brest", enrol_year=1712, age=1712 - by)
        set_family(r, nom="TANGUY", pere_prenom="Hervé",
                   mere_nom="Salaün", mere_prenom="Françoise")
        r["prenom"] = ["Hervé", "Yves"][i]
    # d2,d3 Finistère fillers (d2 stature cohort Tier-A)
    for i in range(2):
        r = new(tier=("A" if i == 0 else "C"), tags={"stature"})
        fill_common(r, company=GOLD_COMPANIES["D"], department="Finistère",
                    commune=fin[(i + 2) % len(fin)], enrol_year=1711 + i, age=23 + i)
        r["nom"] = BG_SURNAMES[(rid * 9) % len(BG_SURNAMES)]
        r["prenom"] = FIRST_NAMES[(rid * 5) % len(FIRST_NAMES)]
    # d4,d5,d6 Morbihan (d4 stature cohort)
    for i in range(3):
        r = new(tier="C", tags=({"stature"} if i == 0 else set()))
        fill_common(r, company=GOLD_COMPANIES["D"], department="Morbihan",
                    commune=mor[i % len(mor)], enrol_year=1710 + i, age=24 + i)
        r["nom"] = BG_SURNAMES[(rid * 7) % len(BG_SURNAMES)]
        r["prenom"] = FIRST_NAMES[(rid * 11) % len(FIRST_NAMES)]
    # d7 VERT-ABSENT son: BLANC Jacques (Seine/Paris) — named father has no record
    r = new(role="VERT-ABSENT", tier="B", tags={"vert_son"})
    fill_common(r, company=GOLD_COMPANIES["D"], department="Seine",
                commune="Paris", enrol_year=1713, age=21)
    set_family(r, nom="BLANC", pere_prenom="Michel")
    r["prenom"] = "Jacques"
    # d8..d11 Seine fillers
    for i in range(4):
        r = new(tier="C")
        fill_common(r, company=GOLD_COMPANIES["D"], department="Seine",
                    commune=D["Seine"]["communes"][i % 3], enrol_year=1710 + (i % 5), age=26 + i)
        r["nom"] = BG_SURNAMES[(rid * 3) % len(BG_SURNAMES)]
        r["prenom"] = FIRST_NAMES[(rid * 7) % len(FIRST_NAMES)]
    # d12,d13 Eure fillers
    for i in range(2):
        r = new(tier="C")
        fill_common(r, company=GOLD_COMPANIES["D"], department="Eure",
                    commune=D["Eure"]["communes"][i % 3], enrol_year=1711 + i, age=28 + i)
        r["nom"] = BG_SURNAMES[(rid * 5) % len(BG_SURNAMES)]
        r["prenom"] = FIRST_NAMES[(rid * 13) % len(FIRST_NAMES)]

    # ----- Vertical-link father records (5, in background units) -----
    def father(case, nom, prenom, birth_year, dep, commune, tier):
        r = new(role=f"father:{case}", tier=tier, tags={"vert_father"})
        age = 28
        fill_common(r, company=BG_COMPANIES[0], department=dep, commune=commune,
                    enrol_year=birth_year + age, age=age, with_parents=True)
        r["nom"] = nom
        r["prenom"] = prenom
        r["naissance_annee"] = str(birth_year)
        r["age"] = str(age)
        return r

    father("VERT-TRUE", "DUPONT", "Pierre", 1658, "Finistère", "Brest", "A")    # gap 30 (Jean 1688)
    father("VERT-YOUNG", "GIRARD", "Mathieu", 1675, "Côtes-du-Nord", "Saint-Brieuc", "A")  # gap 17 (Louis 1692)
    father("VERT-OLD", "ROUX", "Nicolas", 1638, "Bas-Rhin", "Strasbourg", "A")  # gap 52 (Antoine 1690)
    # Decoy homonym for VERT-DECOY: same name as son's named father but gap<=0
    father("VERT-DECOY-homonym", "MOREAU", "Jacques", 1692, "Rhône", "Lyon", "B")  # gap -2 (Pierre 1690)
    # 5th father-era background soldier, no linkage
    r = new(tier="C")
    fill_common(r, company=BG_COMPANIES[1], department="Nord", commune="Douai",
                enrol_year=1688, age=30)
    r["nom"] = "CHARPENTIER"
    r["prenom"] = "Honoré"

    # ----- Mechanics standalone (10) -----
    # m0,m1 homonyms: same nom+prenom, different person
    for i, (dep, com) in enumerate([("Nord", "Lille"), ("Gironde", "Bordeaux")]):
        r = new(tier="B", tags={"homonym"})
        fill_common(r, company=BG_COMPANIES[2 + i], department=dep, commune=com,
                    enrol_year=1709 + i, age=25 + i)
        r["nom"] = "BERNARD"
        r["prenom"] = "Louis"
    # m2 CHALET Jean — RAG record-grounding (RQ-REC-01) + surname+firstname lookup
    # (RQ-NAME-02). Surnom alias retained as a value trap.
    r = new(tier="B", tags={"record_probe"})
    fill_common(r, company=BG_COMPANIES[3], department="Finistère", commune="Morlaix",
                enrol_year=1710, age=24)
    r["nom"] = "CHALET"
    r["prenom"] = "Jean"
    r["surnom"] = "dit Saint-Jean"
    # m3,m4 partial-date: year-only birth
    for i in range(2):
        r = new(tier="C", tags={"partial_date"})
        fill_common(r, company=BG_COMPANIES[4], department="Meurthe", commune="Toul",
                    enrol_year=1711 + i, age=26 + i)
        r["nom"] = BG_SURNAMES[(rid * 5) % len(BG_SURNAMES)]
        r["prenom"] = FIRST_NAMES[(rid * 7) % len(FIRST_NAMES)]
        r["naissance_mois"] = ""
        r["naissance_jour"] = ""
    # m5 accented place
    r = new(tier="C", tags={"accented_place"})
    fill_common(r, company=BG_COMPANIES[5], department="Moselle",
                commune="Brieulles-sur-Meuse", enrol_year=1710, age=27)
    r["nom"] = "DELORME"
    r["prenom"] = "Claude"
    # m6,m7 Corsican with naissance_pieve (planted-only)
    for i, pieve in enumerate(["pieve de Talcini", "pieve d'Orezza"]):
        r = new(tier=("A" if i == 0 else "C"), tags={"corse"})
        fill_common(r, company=BG_COMPANIES[6], department="Corse", commune=("Corte" if i == 0 else "Cervione"),
                    enrol_year=1712 + i, age=24 + i)
        r["nom"] = BG_SURNAMES[(rid * 3) % len(BG_SURNAMES)]
        r["prenom"] = FIRST_NAMES[(rid * 11) % len(FIRST_NAMES)]
        r["naissance_departement"] = "Corse"
        r["naissance_pays"] = "Corse"
        r["naissance_region"] = "Corse"
        r["naissance_pieve"] = pieve
    # m8 CHALET Pierre — RQ-UNANS-REG: has a regiment in COMPLETE; under MASKED the
    # regiment usually drops (tier C, ~15% target) so the correct answer becomes
    # "not recorded" (abstention).
    r = new(tier="C", tags={"unans_probe"})
    fill_common(r, company=BG_COMPANIES[7], department="Isère", commune="Vienne",
                enrol_year=1715, age=30)
    r["nom"] = "CHALET"
    r["prenom"] = "Pierre"
    # m9..m11 MARTIN trio — RQ-NAME-01 (a surname with several bearers)
    for i, pr in enumerate(("Pierre", "Nicolas", "Claude")):
        r = new(tier="C")
        fill_common(r, company=BG_COMPANIES[7], department="Isère", commune="Vienne",
                    enrol_year=1716 + i, age=29 + i)
        r["nom"] = "MARTIN"
        r["prenom"] = pr

    # ----- Background non-clean families (8 records) -----
    # FAM-DECOY-1: same nom+pere_prenom, different birthplace + mother + huge gap
    for i, (by, dep, com, mn) in enumerate([
        (1685, "Rhône", "Lyon", "Royer"), (1715, "Nord", "Lille", "Lambert")]):
        r = new(family="FAM-DECOY-1", tier="B", tags={"decoy_family"})
        fill_common(r, company=BG_COMPANIES[0], department=dep, commune=com,
                    enrol_year=by + 22, age=22)
        set_family(r, nom="RENARD", pere_prenom="Claude", mere_nom=mn,
                   mere_prenom=["Barbe", "Renée"][i])
        r["prenom"] = ["Louis", "Mathieu"][i]
    # FAM-PARTIAL-1: true siblings, one missing birthplace
    for i, by in enumerate((1690, 1692)):
        r = new(family="FAM-PARTIAL-1", tier="B", tags={"partial_family"})
        fill_common(r, company=BG_COMPANIES[1], department="Gironde", commune="Bordeaux",
                    enrol_year=by + 21, age=21)
        set_family(r, nom="FAURE", pere_prenom="René",
                   mere_nom="Thomas", mere_prenom="Catherine")
        r["prenom"] = ["André", "Julien"][i]
        if i == 1:  # missing birthplace even in COMPLETE
            r["naissance_lieu"] = ""
            r["naissance_departement"] = ""
            r["naissance_juridiction"] = ""
            r["naissance_region"] = ""
    # FAM-SINGLEP-1: one father-only, one mother-only, same surname + birthplace
    for i in range(2):
        r = new(family="FAM-SINGLEP-1", tier="B", tags={"singleparent_family"})
        fill_common(r, company=BG_COMPANIES[2], department="Isère", commune="Grenoble",
                    enrol_year=1711 + i, age=22 + i)
        r["nom"] = "ROUSSEL"
        r["prenom"] = ["Pierre", "Jean"][i]
        if i == 0:  # only father recorded
            r["pere_prenom"] = "Joseph"
            r["mere_nom"] = ""
            r["mere_prenom"] = ""
        else:       # only mother recorded
            r["pere_prenom"] = ""
            r["mere_nom"] = "Petit"
            r["mere_prenom"] = "Louise"
    # FAM-NEG-1: same surname, unrelated (different parents)
    for i in range(2):
        r = new(family="FAM-NEG-1", tier="B", tags={"neg_family"})
        fill_common(r, company=BG_COMPANIES[3], department="Eure",
                    commune=["Évreux", "Bernay"][i], enrol_year=1710 + i, age=24 + i)
        set_family(r, nom="MASSON", pere_prenom=["Pierre", "Guillaume"][i],
                   mere_nom=["Durand", "Henry"][i], mere_prenom=["Anne", "Marie"][i])
        r["prenom"] = ["Louis", "François"][i]

    # ----- Complete trajectories (5: birth + enrol + death place) -----
    traj_specs = [
        ("Finistère", "Quimper", 1709, "Bas-Rhin", "Strasbourg", 1720, "A"),
        ("Morbihan", "Vannes", 1710, "Nord", "Lille", 1722, "A"),
        ("Bas-Rhin", "Haguenau", 1711, "Rhône", "Lyon", 1724, "C"),
        ("Gironde", "Bordeaux", 1708, "Seine", "Paris", 1719, "C"),
        ("Nord", "Douai", 1712, "Isère", "Grenoble", 1726, "C"),
    ]
    for i, (bdep, bcom, ey, ddep, dcom, dy, tier) in enumerate(traj_specs):
        r = new(tier=tier, tags={"trajectory"})
        fill_common(r, company=BG_COMPANIES[4 + i % 3], department=bdep, commune=bcom,
                    enrol_year=ey, age=22)
        if i == 0:  # LEROY Guillaume — the named complete-trajectory probe (RQ-MIG-04)
            r["nom"], r["prenom"] = "LEROY", "Guillaume"
        else:
            r["nom"] = BG_SURNAMES[(rid * 3) % len(BG_SURNAMES)]
            r["prenom"] = FIRST_NAMES[(rid * 5) % len(FIRST_NAMES)]
        r["deces_annee"] = str(dy)
        r["deces_lieu"] = dcom
        r["deces_departement"] = ddep

    # ----- Background fillers to reach 180 -----
    while rid < 180:
        r = new(tier="C")
        rg = rng_for(rid)
        dep = BG_DEPARTMENTS[rid % len(BG_DEPARTMENTS)]
        com = rg.choice(DEPARTMENTS[dep]["communes"])
        fill_common(r, company=rg.choice(BG_COMPANIES), department=dep, commune=com,
                    enrol_year=rg.randint(1700, 1720), age=rg.randint(16, 50))
        # draw a name not colliding with reserved father keys
        for _ in range(20):
            nom = rg.choice(BG_SURNAMES)
            prenom = rg.choice(FIRST_NAMES)
            if (nom, prenom) not in blocked_keys:
                break
        r["nom"] = nom
        r["prenom"] = prenom

    assert rid == 180, rid

    # ----- Stature heights (region X Bretagne ~168 cm, region Y Lorraine ~163 cm) -----
    jitter = [-3, -1, 1, 3, 5, -2, 2, 4, 0, -4, 6, -1, 2, 3, -2]
    cohort = [r for r in records if "stature" in r["_tags"]]
    j = 0
    for r in cohort:
        region = region_of(r["naissance_departement"]) if r["naissance_departement"] else "Bretagne"
        base = 168 if region == "Bretagne" else 163
        target = base + jitter[j % len(jitter)]
        j += 1
        p, po, li = height_units(target)
        r["pied"], r["pouce"], r["ligne"] = str(p), str(po), str(li)
        r["taille_metre"] = f"{cm_of(p, po, li) / 100:.2f}"
        if not r["naissance_region"]:
            r["naissance_region"] = region

    # ----- naissance_region on a few extra background records (target ~11%) -----
    extra_region = [r for r in records
                    if not r["naissance_region"] and r["naissance_departement"]
                    and "stature" not in r["_tags"]]
    for r in sorted(extra_region, key=lambda x: x["_rid"])[:8]:
        r["naissance_region"] = region_of(r["naissance_departement"])

    # ----- desertion_annee on a couple of deserters (ultra-rare planted) -----
    for r in records:
        if r["desertion"] == "oui" and r["_tier"] == "A":
            r["desertion_annee"] = str(int(r["enrolement_annee"]) + 3)

    return records


# ---------------------------------------------------------------------------
# Tier rebalancing to exact 18 / 63 / 99
# ---------------------------------------------------------------------------

def balance_tiers(records: list[dict]):
    target = {"A": 18, "B": 63, "C": 99}
    # Forced tiers are already set; fill the remaining quota deterministically.
    forced_idx = set()
    counts = {"A": 0, "B": 0, "C": 0}
    for r in records:
        # records explicitly placed in A or B are treated as forced; C is default
        if r["_tier"] in ("A", "B"):
            forced_idx.add(r["_rid"])
            counts[r["_tier"]] += 1
    # promote background C records to B until B target met (A is fully forced)
    pool = [r for r in records if r["_rid"] not in forced_idx]
    rng = random.Random(SEED)
    rng.shuffle(pool)
    need_b = target["B"] - counts["B"]
    assert counts["A"] == target["A"], f"A tier forced count={counts['A']} != 18"
    assert need_b >= 0, f"too many forced B: {counts['B']}"
    for r in pool[:need_b]:
        r["_tier"] = "B"
    # rest stay C
    final = {"A": 0, "B": 0, "C": 0}
    for r in records:
        final[r["_tier"]] += 1
    assert final == target, final


# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------

def apply_masking(records: list[dict]) -> tuple[list[dict], dict]:
    """Return masked records (deep copies) + masked-survival map for probes."""
    masked = []
    for r in records:
        m = {c: r[c] for c in COLUMNS}
        m["_rid"] = r["_rid"]
        m["_tier"] = r["_tier"]
        m["_tags"] = set(r["_tags"])
        m["_family"] = r["_family"]
        m["_role"] = r["_role"]
        masked.append(m)

    def order_key(rec, field):
        # tier-priority, then a stable per-field hash for within-tier order.
        # md5 (not built-in hash) so ordering is deterministic across processes.
        digest = hashlib.md5(f"{rec['_rid']}|{field}|{SEED}".encode()).digest()
        return (TIER_RANK[rec["_tier"]], int.from_bytes(digest[:4], "big"))

    # Common/mid fields: keep exactly round(target*N), tier-priority first.
    for field, target in MASK_TARGETS.items():
        present = [m for m in masked if m[field] != ""]
        n_keep = min(len(present), round(target * len(masked)))
        present.sort(key=lambda m: order_key(m, field))
        for m in present[n_keep:]:
            m[field] = ""

    # Planted-only fields: keep only the Tier-A planted subset.
    for field in PLANTED_ONLY:
        for m in masked:
            if m[field] != "" and m["_tier"] != "A":
                m[field] = ""

    # masked-survival map for planted probes (§4.2)
    survival = {}
    for r, m in zip(records, masked):
        if r["_tags"]:
            survival[str(r["_rid"])] = {
                "tags": sorted(r["_tags"]),
                "tier": r["_tier"],
                "nom": r["nom"], "prenom": r["prenom"],
            }
    return masked, survival


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def to_dataframe(records: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{c: r[c] for c in COLUMNS} for r in records], columns=COLUMNS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    GOLD.mkdir(parents=True, exist_ok=True)

    records = build_records()
    balance_tiers(records)
    masked, survival = apply_masking(records)

    df_c = to_dataframe(records)
    df_m = to_dataframe(masked)
    df_c.to_csv(OUT / "complete.csv", index=False, encoding="utf-8")
    df_m.to_csv(OUT / "masked.csv", index=False, encoding="utf-8")
    (OUT / "seed.txt").write_text(str(SEED), encoding="utf-8")

    # gold computation lives in gold.py
    import gold as goldmod
    goldmod.compute_all(records, masked, survival, GOLD)

    # pinned toponym gazetteer (§2 toponym enrichment)
    import normalize as normmod
    normmod.write_gazetteer(OUT / "gazetteer.json")

    # question set
    import questions as qmod
    qmod.write_questions(records, masked, OUT, GOLD)

    print(f"Wrote {len(records)} records -> {OUT}")
    print(f"  tiers: " + ", ".join(
        f"{t}={sum(1 for r in records if r['_tier']==t)}" for t in "ABC"))


if __name__ == "__main__":
    main()
