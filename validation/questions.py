"""
Two-layer query design (§6): the Layer-1 reference-query catalogue (the oracle)
and the Layer-2 FR/EN question set, from a single source of truth.

Every intent is authored once with: a canonical Cypher query (Layer 1), a
difficulty `stratum`, a `held_out` flag (query/template split), and a pandas
`gold` function. Gold answers are the pandas computation; the catalogue carries
the canonical Cypher so a graph run can be cross-checked against it
(verify_graph.py) — satisfying the "execute AND match pandas" rule (§2, §9).

Emits:
    corpus/questions.jsonl                 Layer-2 questions (FR/EN)
    corpus/reference_queries/catalogue.json  Layer-1 ref queries + gold
    corpus/gold/answers.json               per-question gold (COMPLETE + MASKED)

Record ids are 0-based row positions; canonical Cypher returns s.line_idx,
which equals the row position for this single-chunk corpus.
"""

from __future__ import annotations

import json
from pathlib import Path

from normalize import norm, resolve_place

GOLD_COMPS = {"compagnie A", "compagnie B", "compagnie C", "compagnie D"}


# --- gold helpers (pandas-side oracle) ---
def _rids(recs, pred):
    return sorted(r["_rid"] for r in recs if pred(r))


def _present_rids(recs, field, pred):
    return sorted(r["_rid"] for r in recs if r[field] != "" and pred(r))


def _eqrids(recs, field, value):
    """Equality matching through the shared norm() fold (§2 'store accented,
    match normalized'). Tolerates unaccented question params."""
    target = norm(value)
    return sorted(r["_rid"] for r in recs if r[field] != "" and norm(r[field]) == target)


def _toponym_rids(recs, place_name):
    """Resolve a FR/EN place label via the pinned gazetteer (P131 hierarchy) and
    return soldiers born in any covered department (norm-matched)."""
    res = resolve_place(place_name)
    if res is None:
        return []
    depts = {norm(d) for d in res["departments"]}
    return sorted(r["_rid"] for r in recs
                  if r["naissance_departement"] != "" and norm(r["naissance_departement"]) in depts)


def _histogram(recs, field, pred):
    from collections import Counter
    return dict(sorted(Counter(r[field] for r in recs if r[field] != "" and pred(r)).items()))


def _mean_height(recs, region):
    vals = [float(r["taille_metre"]) for r in recs
            if r["taille_metre"] != "" and r["naissance_region"] == region]
    if not vals:
        return {"n": 0, "mean_metre": None}
    return {"n": len(vals), "mean_metre": round(sum(vals) / len(vals), 3)}


def _multi_hop_birthplace(recs, nom, prenom):
    target = next((r for r in recs if r["nom"] == nom and r["prenom"] == prenom), None)
    if target is None or target["naissance_lieu"] == "":
        return []
    place = target["naissance_lieu"]
    return sorted(r["_rid"] for r in recs
                  if r["naissance_lieu"] == place and r["_rid"] != target["_rid"])


def _record_field(recs, matricule, field):
    out = [{"rid": r["_rid"], field: r[field]} for r in recs if r["matricule"] == matricule]
    return out


# ---------------------------------------------------------------------------
# The catalogue: one entry per intent.
# Fields: id (ref_query), use_case, stratum, modes, held_out, fr, en, cypher,
#         postproc, schema_dep, result_kind, gold(records)->denotation.
# ---------------------------------------------------------------------------

def _entries(records):
    E = []

    def add(qid, use_case, stratum, modes, fr, en, cypher, gold, *,
            held_out=False, postproc="", schema_dep="Soldier properties",
            result_kind="rid_set", conditions=("COMPLETE", "MASKED")):
        E.append(dict(
            id=qid, ref_query="RQ-" + qid[2:], use_case=use_case, stratum=stratum,
            modes=list(modes), held_out=held_out, fr=fr, en=en, cypher=cypher,
            postproc=postproc, schema_dep=schema_dep, result_kind=result_kind,
            conditions=list(conditions), gold=gold))

    # --- planted anchors, resolved from tags (spec §6.2: never hardcoded) -----
    # Each named question entity is bound to its planted record via the shared
    # gold.py resolver, so the FR/EN text, the canonical Cypher, and the gold all
    # reference the same soldier the generator actually planted.
    from gold import anchor_one

    def A(label, **selectors):
        rec = anchor_one(records, **selectors)
        if rec is None:
            raise ValueError(f"questions.py: unresolved planted anchor {label} ({selectors})")
        return rec

    hub        = A("VERT-TRUE/FAM-CLEAN-1 hub", role="VERT-TRUE")  # DUPONT Jean
    v_young    = A("VERT-YOUNG", role="VERT-YOUNG")                # GIRARD Louis
    v_old      = A("VERT-OLD", role="VERT-OLD")                    # ROUX Antoine
    v_decoy    = A("VERT-DECOY", role="VERT-DECOY")                # MOREAU Pierre
    v_absent   = A("VERT-ABSENT", role="VERT-ABSENT")             # BLANC Jacques
    fam_clean3 = A("FAM-CLEAN-3", family="FAM-CLEAN-3")            # SCHMITT Joseph
    fam_decoy  = A("FAM-DECOY-1", family="FAM-DECOY-1")           # RENARD Louis
    fam_partial = A("FAM-PARTIAL-1", family="FAM-PARTIAL-1")      # FAURE André
    fam_neg    = A("FAM-NEG-1", family="FAM-NEG-1")               # MASSON …
    homonym    = A("homonym", tag="homonym")                     # BERNARD Louis
    rec_probe  = A("record_probe", tag="record_probe")           # CHALET Jean
    unans      = A("unans_probe", tag="unans_probe")             # CHALET Pierre

    def nm(rec):  # (nom, prenom) display pair
        return rec["nom"], rec["prenom"]

    # ---------- Complete-answer (lookup) ----------
    name1_nom = hub["nom"]
    add("Q-NAME-01", "complete", "lookup", ["template", "nl2cypher"],
        f"Quels soldats portent le nom de famille {name1_nom} ?",
        f"Which soldiers have the surname {name1_nom}?",
        f"MATCH (s:Soldier) WHERE s.nom = '{name1_nom}' RETURN s.line_idx AS rid",
        lambda r: _rids(r, lambda x: x["nom"] == name1_nom))
    name2_nom, name2_pre = nm(rec_probe)
    add("Q-NAME-02", "complete", "lookup", ["template", "nl2cypher"],
        f"Quels soldats se nomment {name2_nom} {name2_pre} ?",
        f"Which soldiers are named {name2_nom} {name2_pre}?",
        f"MATCH (s:Soldier) WHERE s.nom='{name2_nom}' AND s.prenom='{name2_pre}' RETURN s.line_idx AS rid",
        lambda r: _rids(r, lambda x: x["nom"] == name2_nom and x["prenom"] == name2_pre))
    add("Q-NAME-03", "complete", "lookup", ["nl2cypher"],
        "Quels soldats ont un nom contenant « LE » (insensible à la casse) ?",
        "Which soldiers have a surname containing 'LE' (case-insensitive)?",
        "MATCH (s:Soldier) WHERE toLower(s.nom) CONTAINS 'le' RETURN s.line_idx AS rid",
        lambda r: _rids(r, lambda x: "le" in x["nom"].lower()), held_out=True)
    add("Q-NAME-04", "complete", "lookup", ["template", "nl2cypher"],
        "Quels soldats portent le nom de famille TANGUY ?",
        "Which soldiers have the surname TANGUY?",
        "MATCH (s:Soldier) WHERE s.nom = 'TANGUY' RETURN s.line_idx AS rid",
        lambda r: _rids(r, lambda x: x["nom"] == "TANGUY"))
    add("Q-COMP-01", "complete", "lookup", ["template", "nl2cypher"],
        "Quels soldats appartiennent à la compagnie A ?",
        "Which soldiers belong to company A?",
        "MATCH (s:Soldier)-[:BELONGS_TO]->(c:Company {nom:'compagnie A'}) RETURN s.line_idx AS rid",
        lambda r: _rids(r, lambda x: x["compagnie"] == "compagnie A"),
        schema_dep="Soldier-[:BELONGS_TO]->Company")
    add("Q-COMP-02", "complete", "lookup", ["template", "nl2cypher"],
        "Quel est le soldat dont le matricule est 1000 ?",
        "Which soldier has matricule 1000?",
        "MATCH (s:Soldier) WHERE s.matricule='1000' RETURN s.line_idx AS rid",
        lambda r: _present_rids(r, "matricule", lambda x: x["matricule"] == "1000"))
    add("Q-COMP-03", "complete", "lookup", ["template", "nl2cypher"],
        "Quels soldats appartiennent à la compagnie D ?",
        "Which soldiers belong to company D?",
        "MATCH (s:Soldier)-[:BELONGS_TO]->(c:Company {nom:'compagnie D'}) RETURN s.line_idx AS rid",
        lambda r: _rids(r, lambda x: x["compagnie"] == "compagnie D"),
        schema_dep="Soldier-[:BELONGS_TO]->Company")
    add("Q-ENR-01", "complete", "lookup", ["template", "nl2cypher"],
        "Quels soldats se sont enrôlés en 1710 ?",
        "Which soldiers enlisted in 1710?",
        "MATCH (s:Soldier) WHERE s.enrolement_annee=1710 RETURN s.line_idx AS rid",
        lambda r: _present_rids(r, "enrolement_annee", lambda x: x["enrolement_annee"] == "1710"))
    add("Q-ENR-03", "complete", "lookup", ["template", "nl2cypher"],
        "Quels soldats se sont enrôlés en 1712 ?",
        "Which soldiers enlisted in 1712?",
        "MATCH (s:Soldier) WHERE s.enrolement_annee=1712 RETURN s.line_idx AS rid",
        lambda r: _present_rids(r, "enrolement_annee", lambda x: x["enrolement_annee"] == "1712"))
    add("Q-BPL-01", "complete", "lookup", ["template", "nl2cypher"],
        "Quels soldats sont nés dans le département du Finistère ?",
        "Which soldiers were born in the Finistère department?",
        "MATCH (s:Soldier) WHERE s.naissance_departement='Finistère' RETURN s.line_idx AS rid",
        lambda r: _present_rids(r, "naissance_departement", lambda x: x["naissance_departement"] == "Finistère"))
    add("Q-BPL-02", "complete", "lookup", ["template", "nl2cypher"],
        "Quels soldats sont nés à Brest ?",
        "Which soldiers were born in Brest?",
        "MATCH (s:Soldier) WHERE s.naissance_lieu='Brest' RETURN s.line_idx AS rid",
        lambda r: _present_rids(r, "naissance_lieu", lambda x: x["naissance_lieu"] == "Brest"))
    add("Q-BPL-03", "complete", "lookup", ["template", "nl2cypher"],
        "Quels soldats sont nés à Paris ?",
        "Which soldiers were born in Paris?",
        "MATCH (s:Soldier) WHERE s.naissance_lieu='Paris' RETURN s.line_idx AS rid",
        lambda r: _present_rids(r, "naissance_lieu", lambda x: x["naissance_lieu"] == "Paris"))
    add("Q-RAG-01", "complete", "lookup", ["rag"],
        f"Parlez-moi du soldat {name2_nom} {name2_pre}.",
        f"Tell me about the soldier {name2_nom} {name2_pre}.",
        f"MATCH (s:Soldier) WHERE s.nom='{name2_nom}' AND s.prenom='{name2_pre}' RETURN s.line_idx AS rid",
        lambda r: _rids(r, lambda x: x["nom"] == name2_nom and x["prenom"] == name2_pre),
        result_kind="rag_target")

    # ---------- Bounded-answer ----------
    add("Q-ENR-02", "bounded", "lookup", ["template", "nl2cypher"],
        "Quels soldats se sont enrôlés entre 1708 et 1712 ?",
        "Which soldiers enlisted between 1708 and 1712?",
        "MATCH (s:Soldier) WHERE s.enrolement_annee>=1708 AND s.enrolement_annee<=1712 RETURN s.line_idx AS rid",
        lambda r: _present_rids(r, "enrolement_annee", lambda x: 1708 <= int(x["enrolement_annee"]) <= 1712),
        held_out=True)
    add("Q-DTH-01", "bounded", "lookup", ["template", "nl2cypher"],
        "Quels soldats sont morts en 1720 ?",
        "Which soldiers died in 1720?",
        "MATCH (s:Soldier) WHERE s.deces_annee=1720 RETURN s.line_idx AS rid",
        lambda r: _present_rids(r, "deces_annee", lambda x: x["deces_annee"] == "1720"))
    add("Q-DTH-02", "bounded", "lookup", ["template", "nl2cypher"],
        "Quels soldats sont morts après 1720 ?",
        "Which soldiers died after 1720?",
        "MATCH (s:Soldier) WHERE s.deces_annee>1720 RETURN s.line_idx AS rid",
        lambda r: _present_rids(r, "deces_annee", lambda x: int(x["deces_annee"]) > 1720),
        held_out=True)
    add("Q-RNK-01", "bounded", "lookup", ["template", "nl2cypher"],
        "Quels soldats ont pour grade final « sergent » ?",
        "Which soldiers have final rank 'sergent'?",
        "MATCH (s:Soldier) WHERE s.grade_final='sergent' RETURN s.line_idx AS rid",
        lambda r: _present_rids(r, "grade_final", lambda x: x["grade_final"] == "sergent"))
    add("Q-RNK-02", "bounded", "lookup", ["template", "nl2cypher"],
        "Quels soldats ont pour grade final « caporal » ?",
        "Which soldiers have final rank 'caporal'?",
        "MATCH (s:Soldier) WHERE s.grade_final='caporal' RETURN s.line_idx AS rid",
        lambda r: _present_rids(r, "grade_final", lambda x: x["grade_final"] == "caporal"))
    par_nom, par_pre = nm(hub)
    add("Q-PAR-01", "bounded", "lookup", ["template", "nl2cypher"],
        f"Qui sont les parents du soldat {par_nom} {par_pre} ?",
        f"Who are the parents of the soldier {par_nom} {par_pre}?",
        f"MATCH (s:Soldier) WHERE s.nom='{par_nom}' AND s.prenom='{par_pre}' "
        "RETURN s.pere_prenom, s.mere_nom, s.mere_prenom",
        lambda r: [{"rid": x["_rid"], "pere_prenom": x["pere_prenom"],
                    "mere_nom": x["mere_nom"], "mere_prenom": x["mere_prenom"]}
                   for x in r if x["nom"] == par_nom and x["prenom"] == par_pre],
        result_kind="record_fields")
    add("Q-PRO-01", "bounded", "lookup", ["template", "nl2cypher"],
        "Quels soldats étaient laboureurs de profession ?",
        "Which soldiers were labourers by profession?",
        "MATCH (s:Soldier) WHERE s.profession='laboureur' RETURN s.line_idx AS rid",
        lambda r: _present_rids(r, "profession", lambda x: x["profession"] == "laboureur"))
    add("Q-DES-01", "bounded", "lookup", ["template", "nl2cypher"],
        "Quels soldats ont déserté ?",
        "Which soldiers deserted?",
        "MATCH (s:Soldier) WHERE s.desertion='oui' RETURN s.line_idx AS rid",
        lambda r: _present_rids(r, "desertion", lambda x: x["desertion"] == "oui"))
    add("Q-REG-01", "bounded", "lookup", ["template", "nl2cypher"],
        "Quels soldats ont servi au régiment de Picardie ?",
        "Which soldiers served in the régiment de Picardie?",
        "MATCH (s:Soldier)-[:SERVED_IN]->(rg:Regiment {nom:'régiment de Picardie'}) RETURN s.line_idx AS rid",
        lambda r: _present_rids(r, "regiment", lambda x: x["regiment"] == "régiment de Picardie"),
        schema_dep="Soldier-[:SERVED_IN]->Regiment")

    # ---------- Genealogy: sibling/family (multi-hop) ----------
    sib_cypher = (
        "// requires parent MERGE (see §8 prerequisite)\n"
        "MATCH (x:Soldier {{nom:'{nom}', prenom:'{prenom}'}})-[:CHILD_OF]->(p:Person)<-[:CHILD_OF]-(b:Soldier) "
        "RETURN b.line_idx AS rid")
    sib1_nom, sib1_pre = nm(hub)
    add("Q-SIB-01", "genealogy", "multi_hop", ["nl2cypher", "graph"],
        f"Quels sont les frères du soldat {sib1_nom} {sib1_pre} ?",
        f"Who are the brothers of the soldier {sib1_nom} {sib1_pre}?",
        sib_cypher.format(nom=sib1_nom, prenom=sib1_pre),
        lambda r: _rids(r, lambda x: x["_family"] == "FAM-CLEAN-1"),
        postproc="cluster by (nom, pere_prenom, mere_nom, mere_prenom) + birthplace corroboration",
        schema_dep="Soldier-[:CHILD_OF]->Person (MERGE on composite parent identity)")
    add("Q-SIB-02", "genealogy", "multi_hop", ["graph", "rag"],
        "Listez toutes les familles (fratries) de la compagnie A.",
        "List all families (sibling sets) in company A.",
        "MATCH (s:Soldier)-[:BELONGS_TO]->(:Company {nom:'compagnie A'}) "
        "MATCH (s)-[:CHILD_OF]->(p:Person)<-[:CHILD_OF]-(s2:Soldier) RETURN s.line_idx, s2.line_idx",
        lambda r: {"FAM-CLEAN-1": _rids(r, lambda x: x["_family"] == "FAM-CLEAN-1"),
                   "FAM-CLEAN-2": _rids(r, lambda x: x["_family"] == "FAM-CLEAN-2")},
        result_kind="partition",
        postproc="group into equivalence classes; score with B³",
        schema_dep="Soldier-[:CHILD_OF]->Person (MERGE)")
    sib3_nom, sib3_pre = nm(fam_decoy)
    add("Q-SIB-03", "genealogy", "multi_hop", ["graph", "nl2cypher"],
        f"Le soldat {sib3_nom} {sib3_pre} a-t-il des frères dans le corpus ?",
        f"Does the soldier {sib3_nom} {sib3_pre} have brothers in the corpus?",
        sib_cypher.format(nom=sib3_nom, prenom=sib3_pre),
        lambda r: [],  # FAM-DECOY must NOT merge
        result_kind="false_merge",
        postproc="corroboration (birthplace + birth-year span) must reject the merge")
    sib4_nom, sib4_pre = nm(fam_partial)
    add("Q-SIB-04", "genealogy", "multi_hop", ["graph", "nl2cypher"],
        f"Quels sont les frères du soldat {sib4_nom} {sib4_pre} (un frère sans lieu de naissance) ?",
        f"Who are the brothers of soldier {sib4_nom} {sib4_pre} (one brother lacks a birthplace)?",
        sib_cypher.format(nom=sib4_nom, prenom=sib4_pre),
        lambda r: _rids(r, lambda x: x["_family"] == "FAM-PARTIAL-1"),
        postproc="name-only fallback, flagged lower-confidence")
    sib5_nom = fam_neg["nom"]
    add("Q-SIB-05", "genealogy", "multi_hop", ["graph", "nl2cypher"],
        f"Les soldats nommés {sib5_nom} forment-ils une seule famille ?",
        f"Do the soldiers named {sib5_nom} form a single family?",
        f"MATCH (a:Soldier {{nom:'{sib5_nom}'}}), (b:Soldier {{nom:'{sib5_nom}'}}) WHERE a<>b RETURN a.line_idx, b.line_idx",
        lambda r: [],  # FAM-NEG: same surname, unrelated
        result_kind="false_merge",
        postproc="different parents -> must not merge")
    sib6_nom, sib6_pre = nm(fam_clean3)
    add("Q-SIB-06", "genealogy", "multi_hop", ["graph", "nl2cypher"],
        f"Quels sont les frères du soldat {sib6_nom} {sib6_pre} ?",
        f"Who are the brothers of soldier {sib6_nom} {sib6_pre}?",
        sib_cypher.format(nom=sib6_nom, prenom=sib6_pre),
        lambda r: _rids(r, lambda x: x["_family"] == "FAM-CLEAN-3"))

    # ---------- Genealogy: vertical linkage (multi-hop) ----------
    vert_cypher = (
        "MATCH (son:Soldier {{nom:'{nom}', prenom:'{prenom}'}}) "
        "MATCH (f:Soldier) WHERE f.nom=son.nom AND f.prenom=son.pere_prenom AND f<>son "
        "RETURN f.line_idx AS rid, son.naissance_annee - f.naissance_annee AS gap")
    vert_pp = "rank candidates by soft-gap weight w(g); admit w>0, reject w=0"
    vt_nom, vt_pre = nm(hub)
    add("Q-VERT-01", "genealogy", "multi_hop", ["graph", "nl2cypher"],
        f"Trouvez le dossier du père du soldat {vt_nom} {vt_pre}.",
        f"Find the record of the father of soldier {vt_nom} {vt_pre}.",
        vert_cypher.format(nom=vt_nom, prenom=vt_pre),
        lambda r: _vert_father(r, vt_nom, vt_pre), result_kind="linkage", postproc=vert_pp)
    vd_nom, vd_pre = nm(v_decoy)
    add("Q-VERT-02", "genealogy", "multi_hop", ["graph", "nl2cypher"],
        f"Le soldat {vd_nom} {vd_pre} peut-il être relié à un dossier de père plausible ?",
        f"Can soldier {vd_nom} {vd_pre} be linked to a plausible father record?",
        vert_cypher.format(nom=vd_nom, prenom=vd_pre),
        lambda r: _vert_father(r, vd_nom, vd_pre), result_kind="linkage", postproc=vert_pp)
    vy_nom, vy_pre = nm(v_young)
    add("Q-VERT-03", "genealogy", "multi_hop", ["graph", "nl2cypher"],
        f"Trouvez le père du soldat {vy_nom} {vy_pre} (faible écart générationnel).",
        f"Find the father of soldier {vy_nom} {vy_pre} (small generational gap).",
        vert_cypher.format(nom=vy_nom, prenom=vy_pre),
        lambda r: _vert_father(r, vy_nom, vy_pre), result_kind="linkage", postproc=vert_pp)
    vo_nom, vo_pre = nm(v_old)
    add("Q-VERT-04", "genealogy", "multi_hop", ["graph", "nl2cypher"],
        f"Trouvez le père du soldat {vo_nom} {vo_pre} (grand écart générationnel).",
        f"Find the father of soldier {vo_nom} {vo_pre} (large generational gap).",
        vert_cypher.format(nom=vo_nom, prenom=vo_pre),
        lambda r: _vert_father(r, vo_nom, vo_pre), result_kind="linkage", postproc=vert_pp)
    va_nom, va_pre = nm(v_absent)
    add("Q-VERT-05", "genealogy", "multi_hop", ["graph", "nl2cypher"],
        f"Le soldat {va_nom} {va_pre} a-t-il un dossier de père dans le corpus ?",
        f"Does soldier {va_nom} {va_pre} have a father record in the corpus?",
        vert_cypher.format(nom=va_nom, prenom=va_pre),
        lambda r: _vert_father(r, va_nom, va_pre), result_kind="linkage", postproc=vert_pp)

    # ---------- Migration (aggregation / multi-hop) ----------
    add("Q-MIG-01", "migration", "aggregation", ["template", "nl2cypher"],
        "Où sont nés les soldats de la compagnie A ? (répartition par département)",
        "Where were the soldiers of company A born? (distribution by department)",
        "MATCH (s:Soldier {compagnie:'compagnie A'}) WHERE s.naissance_departement IS NOT NULL "
        "RETURN s.naissance_departement AS dept, count(*) AS n ORDER BY dept",
        lambda r: _histogram(r, "naissance_departement", lambda x: x["compagnie"] == "compagnie A"),
        result_kind="histogram")
    add("Q-MIG-02", "migration", "aggregation", ["nl2cypher"],
        "Quelle est la répartition par département de naissance de la cohorte enrôlée en 1710 ?",
        "What is the birth-department distribution of the 1710 enlistment cohort?",
        "MATCH (s:Soldier) WHERE s.enrolement_annee=1710 AND s.naissance_departement IS NOT NULL "
        "RETURN s.naissance_departement AS dept, count(*) AS n ORDER BY dept",
        lambda r: _histogram(r, "naissance_departement",
                             lambda x: x["compagnie"] in GOLD_COMPS and x["enrolement_annee"] == "1710"),
        result_kind="histogram", postproc="restricted to gold companies A–D")
    add("Q-MIG-03", "migration", "aggregation", ["rag", "nl2cypher"],
        "Comparez l'origine géographique des compagnies A et B.",
        "Compare the geographic origins of companies A and B.",
        "MATCH (s:Soldier) WHERE s.compagnie IN ['compagnie A','compagnie B'] "
        "RETURN s.compagnie, s.naissance_departement AS dept, count(*) AS n",
        lambda r: {"compagnie A": _histogram(r, "naissance_departement", lambda x: x["compagnie"] == "compagnie A"),
                   "compagnie B": _histogram(r, "naissance_departement", lambda x: x["compagnie"] == "compagnie B")},
        result_kind="histogram_pair", held_out=True)
    add("Q-MIG-04", "migration", "multi_hop", ["nl2cypher", "graph"],
        "Tracez le parcours naissance → décès des soldats à trajectoire complète.",
        "Trace the birth → death path of the complete-trajectory soldiers.",
        "MATCH (s:Soldier) WHERE s.naissance_departement IS NOT NULL AND s.deces_departement IS NOT NULL "
        "RETURN s.line_idx AS rid, s.naissance_departement, s.deces_departement",
        lambda r: _rids(r, lambda x: x["naissance_departement"] != "" and x["deces_departement"] != ""),
        result_kind="trajectory")
    add("Q-MIG-05", "migration", "aggregation", ["nl2cypher"],
        "Combien de soldats de la compagnie A sont nés dans le Finistère ?",
        "How many of company A's soldiers were born in Finistère?",
        "MATCH (s:Soldier {compagnie:'compagnie A', naissance_departement:'Finistère'}) RETURN count(*) AS n",
        lambda r: {"count": len(_present_rids(r, "naissance_departement",
                   lambda x: x["compagnie"] == "compagnie A" and x["naissance_departement"] == "Finistère"))},
        result_kind="count")

    # ---------- Anthropometric ----------
    add("Q-ANTH-01", "stature", "aggregation", ["nl2cypher", "rag"],
        "Quelle est la taille moyenne des soldats nés en Bretagne (région) ?",
        "What is the average height of soldiers born in the Bretagne region?",
        "MATCH (s:Soldier) WHERE s.naissance_region='Bretagne' AND s.taille_metre IS NOT NULL "
        "RETURN avg(toFloat(s.taille_metre)) AS mean_metre, count(*) AS n",
        lambda r: _mean_height(r, "Bretagne"), result_kind="aggregate")
    add("Q-ANTH-02", "stature", "lookup", ["template", "nl2cypher"],
        "Quels soldats mesurent plus de 170 cm ?",
        "Which soldiers are taller than 170 cm?",
        "MATCH (s:Soldier) WHERE toFloat(s.taille_metre) > 1.70 RETURN s.line_idx AS rid",
        lambda r: _present_rids(r, "taille_metre", lambda x: float(x["taille_metre"]) > 1.70))
    add("Q-ANTH-03", "stature", "aggregation", ["nl2cypher"],
        "Comparez la taille moyenne des soldats nés en Bretagne et en Lorraine.",
        "Compare the mean stature of soldiers born in Bretagne vs Lorraine.",
        "MATCH (s:Soldier) WHERE s.naissance_region IN ['Bretagne','Lorraine'] AND s.taille_metre IS NOT NULL "
        "RETURN s.naissance_region, avg(toFloat(s.taille_metre)) AS mean_metre",
        lambda r: {"Bretagne": _mean_height(r, "Bretagne"), "Lorraine": _mean_height(r, "Lorraine")},
        result_kind="aggregate_pair")

    # ---------- Cross-lingual / toponym normalization (§2, §6.2) ----------
    # EN "Brittany" resolves via the pinned gazetteer to region Bretagne, then via
    # P131 to its departments (Finistère / Côtes-du-Nord / Morbihan).
    add("Q-XLING-01", "migration", "multi_hop", ["nl2cypher", "rag"],
        "Quels soldats sont nés en Bretagne ?",
        "Which soldiers were born in Brittany?",
        "// gazetteer: resolve 'Brittany'->Bretagne (Q12130)->P131 departments\n"
        "MATCH (s:Soldier)-[:BORN_IN]->(:Place)-[:P131*]->(r:Place {wikidata_qid:'Q12130'}) "
        "RETURN s.line_idx AS rid",
        lambda r: _toponym_rids(r, "Brittany"),
        result_kind="rid_set",
        postproc="Layer-M gazetteer resolution: EN label -> FR region -> P131 departments",
        schema_dep="Place.wikidata_qid + P131 hierarchy (pinned gazetteer)")

    # ---------- Matching-normalization fold tests (§2) ----------
    add("Q-FOLD-01", "complete", "lookup", ["template", "nl2cypher"],
        "Quels soldats sont nes dans le departement des Cotes-du-Nord ?",  # intentionally unaccented
        "Which soldiers were born in the Cotes-du-Nord department?",
        "MATCH (s:Soldier) WHERE s.naissance_departement_norm = 'cotesdunord' RETURN s.line_idx AS rid",
        lambda r: _eqrids(r, "naissance_departement", "Cotes-du-Nord"),
        schema_dep="Soldier.naissance_departement_norm (norm() shadow at ingest)",
        postproc="unaccented param 'Cotes-du-Nord' folds onto 'Côtes-du-Nord'")
    add("Q-FOLD-02", "bounded", "lookup", ["template", "nl2cypher"],
        "Quels soldats portent le prenom Rene ?",  # intentionally unaccented (René)
        "Which soldiers have the first name Rene?",
        "MATCH (s:Soldier) WHERE s.prenom_norm = 'rene' RETURN s.line_idx AS rid",
        lambda r: _eqrids(r, "prenom", "Rene"),
        schema_dep="Soldier.prenom_norm (norm() shadow at ingest)",
        postproc="unaccented param 'Rene' folds onto 'René'")

    # ---------- Mechanics ----------
    dis_nom, dis_pre = nm(homonym)
    add("Q-MECH-DIS", "mechanics", "lookup", ["nl2cypher", "rag"],
        f"Il y a deux soldats nommés {dis_nom} {dis_pre} : distinguez-les par leur lieu de naissance.",
        f"There are two soldiers named {dis_nom} {dis_pre}: distinguish them by birthplace.",
        f"MATCH (s:Soldier {{nom:'{dis_nom}', prenom:'{dis_pre}'}}) RETURN s.line_idx AS rid, s.naissance_lieu",
        lambda r: [{"rid": x["_rid"], "naissance_lieu": x["naissance_lieu"],
                    "naissance_departement": x["naissance_departement"]}
                   for x in r if x["nom"] == dis_nom and x["prenom"] == dis_pre],
        result_kind="disambiguation")
    add("Q-MECH-AGG", "mechanics", "aggregation", ["template", "nl2cypher"],
        "Combien de soldats compte la compagnie A ?",
        "How many soldiers are in company A?",
        "MATCH (s:Soldier {compagnie:'compagnie A'}) RETURN count(*) AS n",
        lambda r: {"count": len(_rids(r, lambda x: x["compagnie"] == "compagnie A"))},
        result_kind="count")
    multi_nom, multi_pre = nm(hub)
    add("Q-MECH-MULTI", "mechanics", "multi_hop", ["nl2cypher", "graph"],
        f"Quels autres soldats sont nés au même endroit que {multi_nom} {multi_pre} ?",
        f"Which other soldiers were born in the same place as {multi_nom} {multi_pre}?",
        f"MATCH (x:Soldier {{nom:'{multi_nom}', prenom:'{multi_pre}'}})-[:BORN_IN]->(p:Place)<-[:BORN_IN]-(o:Soldier) "
        "RETURN o.line_idx AS rid",
        lambda r: _multi_hop_birthplace(r, multi_nom, multi_pre),
        schema_dep="Soldier-[:BORN_IN]->Place")
    add("Q-MECH-SURNOM", "mechanics", "lookup", ["nl2cypher", "rag"],
        "Quel soldat porte le surnom « dit Saint-Jean » ?",
        "Which soldier has the nickname 'dit Saint-Jean'?",
        "MATCH (s:Soldier) WHERE s.surnom='dit Saint-Jean' RETURN s.line_idx AS rid",
        lambda r: _present_rids(r, "surnom", lambda x: x["surnom"] == "dit Saint-Jean"))
    add("Q-MECH-CORSE", "mechanics", "lookup", ["nl2cypher", "rag"],
        "Quels soldats sont nés en Corse (avec une pieve renseignée) ?",
        "Which soldiers were born in Corse (with a recorded pieve)?",
        "MATCH (s:Soldier) WHERE s.naissance_pieve IS NOT NULL RETURN s.line_idx AS rid",
        lambda r: _present_rids(r, "naissance_pieve", lambda x: x["naissance_pieve"] != ""))

    # ---------- Unanswerable (abstention rewarded) ----------
    add("Q-MECH-ZERO-01", "mechanics", "unanswerable", ["template", "nl2cypher", "rag"],
        "Quels soldats ont pour grade final « capitaine » ?",
        "Which soldiers have final rank 'capitaine'?",
        "MATCH (s:Soldier) WHERE s.grade_final='capitaine' RETURN s.line_idx AS rid",
        lambda r: _present_rids(r, "grade_final", lambda x: x["grade_final"] == "capitaine"))
    add("Q-MECH-ZERO-02", "mechanics", "unanswerable", ["template", "nl2cypher", "rag"],
        "Quels soldats portent le nom de famille BONAPARTE ?",
        "Which soldiers have the surname BONAPARTE?",
        "MATCH (s:Soldier) WHERE s.nom='BONAPARTE' RETURN s.line_idx AS rid",
        lambda r: _rids(r, lambda x: x["nom"] == "BONAPARTE"))
    unans_nom, unans_pre = nm(unans)
    add("Q-UNANS-REG", "mechanics", "unanswerable", ["template", "nl2cypher", "rag"],
        f"Dans quel régiment a servi le soldat {unans_nom} {unans_pre} ?",
        f"In which regiment did soldier {unans_nom} {unans_pre} serve?",
        f"MATCH (s:Soldier {{nom:'{unans_nom}', prenom:'{unans_pre}'}}) RETURN s.line_idx AS rid, s.regiment",
        lambda r: [{"rid": x["_rid"], "regiment": x["regiment"]}
                   for x in r if x["nom"] == unans_nom and x["prenom"] == unans_pre and x["regiment"] != ""],
        result_kind="record_fields",
        postproc="regiment ~15% recorded; abstain ('not recorded') rather than fabricate when absent")

    # ---------- Cross-mode (same intent, multiple engines) ----------
    add("Q-XMODE-01", "crossmode", "lookup", ["template", "nl2cypher"],
        "Quels soldats appartiennent à la compagnie B ?",
        "Which soldiers belong to company B?",
        "MATCH (s:Soldier)-[:BELONGS_TO]->(c:Company {nom:'compagnie B'}) RETURN s.line_idx AS rid",
        lambda r: _rids(r, lambda x: x["compagnie"] == "compagnie B"),
        schema_dep="Soldier-[:BELONGS_TO]->Company")
    add("Q-XMODE-02", "crossmode", "lookup", ["template", "nl2cypher"],
        "Quels soldats sont nés dans le département de la Moselle ?",
        "Which soldiers were born in the Moselle department?",
        "MATCH (s:Soldier) WHERE s.naissance_departement='Moselle' RETURN s.line_idx AS rid",
        lambda r: _present_rids(r, "naissance_departement", lambda x: x["naissance_departement"] == "Moselle"))
    add("Q-XMODE-03", "crossmode", "lookup", ["template", "nl2cypher"],
        "Quels soldats appartiennent à la compagnie C ?",
        "Which soldiers belong to company C?",
        "MATCH (s:Soldier)-[:BELONGS_TO]->(c:Company {nom:'compagnie C'}) RETURN s.line_idx AS rid",
        lambda r: _rids(r, lambda x: x["compagnie"] == "compagnie C"),
        schema_dep="Soldier-[:BELONGS_TO]->Company")

    return E


def _vert_father(records, nom, prenom):
    """Expected father rid (or None) via the soft-gap rule — Layer-1 post-proc."""
    from gold import w_gap
    son = next((r for r in records if r["nom"] == nom and r["prenom"] == prenom), None)
    if son is None or son["naissance_annee"] == "":
        return None
    son_by = int(son["naissance_annee"])
    best = None
    for f in records:
        if f["_rid"] == son["_rid"]:
            continue
        if f["nom"] == son["nom"] and f["prenom"] == son["pere_prenom"] and f["naissance_annee"] != "":
            g = son_by - int(f["naissance_annee"])
            w = w_gap(g)
            if w > 0 and (best is None or w > best[1]):
                best = (f["_rid"], w)
    return best[0] if best else None


# ---------------------------------------------------------------------------

def build_questions(records, masked):
    entries = _entries(records)
    jsonl, answers, catalogue = [], {}, []
    for e in entries:
        gold_c = e["gold"](records) if "COMPLETE" in e["conditions"] else None
        gold_m = e["gold"](masked) if "MASKED" in e["conditions"] else None
        jsonl.append({
            "id": e["id"], "use_case": e["use_case"], "stratum": e["stratum"],
            "modes": e["modes"], "ref_query": e["ref_query"], "held_out": e["held_out"],
            "fr": e["fr"], "en": e["en"], "gold_ref": "gold/answers.json",
            "conditions": e["conditions"],
        })
        answers[e["id"]] = {
            "use_case": e["use_case"], "stratum": e["stratum"],
            "ref_query": e["ref_query"], "result_kind": e["result_kind"],
            "complete": gold_c, "masked": gold_m,
        }
        catalogue.append({
            "ref_query": e["ref_query"], "intent_en": e["en"], "use_case": e["use_case"],
            "stratum": e["stratum"], "held_out": e["held_out"], "result_kind": e["result_kind"],
            "cypher": e["cypher"], "postproc": e["postproc"], "schema_dep": e["schema_dep"],
            "verified_pandas": True, "verified_graph": None,
            "gold_complete": gold_c, "gold_masked": gold_m,
        })
    return jsonl, answers, catalogue


def write_questions(records, masked, out_dir: Path, gold_dir: Path):
    jsonl, answers, catalogue = build_questions(records, masked)
    with (out_dir / "questions.jsonl").open("w", encoding="utf-8") as f:
        for rec in jsonl:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    (gold_dir / "answers.json").write_text(
        json.dumps(answers, ensure_ascii=False, indent=2), encoding="utf-8")
    refdir = out_dir / "reference_queries"
    refdir.mkdir(parents=True, exist_ok=True)
    (refdir / "catalogue.json").write_text(
        json.dumps(catalogue, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonl, answers, catalogue
