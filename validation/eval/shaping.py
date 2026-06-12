"""
Shape raw live-engine rows into the catalogue ``result_kind`` shape.

A live engine (template / nl2cypher) returns arbitrary Neo4j rows. This module
turns them into the same structure the oracle gold uses, so the metrics apply.
Two strategies, per kind:

  - **parse** — if the generated query already aggregated (a ``{dept, n}`` /
    ``{avg, n}`` row), read it directly;
  - **reconcile** — otherwise map rows back to corpus ``rid``s (by matricule then
    name) and compute the structure from the corpus.

For **linkage** and **partition** the catalogue defines a deterministic
post-processing module (soft-gap ``w()``; parent-key clustering). Per the
validation spec (§7.1, "Scoring linkage & partition"), that module is shared
with the oracle and run **end-to-end on the system's retrieved rows** — so the
generated query supplies the candidate set and the shared module makes the
decision. The runner additionally reports **retrieval recall** (did the query
surface the right candidates?) to separate NL2Cypher's contribution from the
decision step.

``shape()`` returns ``(prediction, retrieved_rids)``. ``prediction`` is ``None``
when the rows cannot be shaped for the kind (reported as ``unparseable``).
"""

from __future__ import annotations

from collections import Counter, defaultdict

from .reference import _as_int, w_gap
from .text import norm

# Engine helpers are imported lazily inside shape() to avoid an import cycle
# (engines.py imports this module).

# Sentinel: the rows could not be shaped into this kind (distinct from a valid
# empty/None answer, e.g. linkage legitimately returning None = "no father").
UNPARSEABLE = object()


# --------------------------------------------------------------------------- #
# row parsing helpers                                                          #
# --------------------------------------------------------------------------- #

def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    return None


def _parse_label_counts(rows):
    """Rows that already pair a label with a count -> {label: int}, else None.

    Gold histograms are keyed by *department*, so when the aggregated rows carry a
    department column (even alongside lieu/pays) we key on it and sum."""
    out = {}
    for row in rows:
        nums = [(k, v) for k, v in row.items() if _num(v) is not None]
        strs = [(k, v) for k, v in row.items() if isinstance(v, str) and v.strip()]
        if len(nums) != 1 or not strs:
            return None
        label = None
        for pref in ("depart", "region"):
            for k, v in strs:
                if pref in k.lower():
                    label = v
                    break
            if label is not None:
                break
        if label is None:
            label = strs[0][1]
        out[label] = out.get(label, 0) + int(nums[0][1])
    return out or None


def _candidate_rids(rows, corpus):
    """Reconcile every (nom, prenom) column family in the rows to corpus rids.

    Handles arbitrary aliases — bare nom/prenom, s.nom/s.prenom,
    father_nom/father_prenom, cand.nom/cand.prenom — so linkage can pick up a
    father returned under any column name."""
    rids = set()
    for row in rows:
        cols = {k.lower(): v for k, v in row.items() if isinstance(v, str) and v.strip()}
        nom_cols = [k for k in cols if k.endswith("nom") and "prenom" not in k and "surnom" not in k]
        pre_cols = [k for k in cols if "prenom" in k]
        for nk in nom_cols:
            prefix = nk[:-3].rstrip("._ ")
            pk = next((p for p in pre_cols if p[:p.lower().find("prenom")].rstrip("._ ") == prefix), None)
            for rid in corpus.find(cols[nk], cols.get(pk) if pk else None):
                rids.add(rid)
    return rids


def _parse_mean(rows):
    """A single aggregated mean/avg (+ optional n) row -> {n, mean_cm}, else None."""
    if len(rows) != 1:
        return None
    row = rows[0]
    mean = n = None
    for k, v in row.items():
        nv = _num(v)
        if nv is None:
            continue
        kl = k.lower()
        if any(t in kl for t in ("avg", "mean", "moyen", "taille", "height")):
            mean = float(nv)
        elif any(t in kl for t in ("count", "n", "total", "nombre")):
            n = int(nv)
    if mean is None:
        return None
    # if the mean looks like metres, lift to cm
    if mean < 3:
        mean *= 100.0
    return {"n": n, "mean_cm": round(mean, 1)}


def _field(row, *needles):
    for k, v in row.items():
        kl = k.lower()
        if any(nd in kl for nd in needles):
            return v if (v is None or isinstance(v, str)) else str(v)
    return None


# --------------------------------------------------------------------------- #
# per-kind shapers                                                             #
# --------------------------------------------------------------------------- #

def _hist_from_rids(corpus, rids, field="naissance_departement"):
    return dict(sorted(Counter(corpus.g(r, field) for r in rids if corpus.g(r, field)).items()))


def _region_mean_from_rids(corpus, rids, region):
    from .reference import _region_mean  # reuse the exact oracle computation scope
    # restrict the oracle's region computation to the retrieved rids
    target = norm(region)
    depts = {norm(d) for d in corpus.topo.departments_for(region)}
    vals = []
    for r in rids:
        if not corpus.has_height(r):
            continue
        if norm(corpus.region_of(r)) == target or norm(corpus.g(r, "naissance_departement")) in depts:
            cm = corpus.height_cm(r)
            if cm is not None:
                vals.append(cm)
    if not vals:
        return {"n": 0, "mean_cm": None}
    return {"n": len(vals), "mean_cm": round(sum(vals) / len(vals), 1)}


def _shape_linkage(retrieved, corpus, params):
    sons = corpus.find(params["nom"], params["prenom"])
    if not sons:
        return None
    s = sons[0]
    son_birth = _as_int(corpus.g(s, "naissance_annee"))
    pere = corpus.g(s, "pere_prenom")
    best, bw = None, 0.0
    for r in retrieved:
        if r == s:
            continue
        if norm(corpus.g(r, "nom")) == norm(corpus.g(s, "nom")) and pere \
                and norm(corpus.g(r, "prenom")) == norm(pere):
            fb = _as_int(corpus.g(r, "naissance_annee"))
            gap = (son_birth - fb) if (son_birth is not None and fb is not None) else None
            w = w_gap(gap)
            if w > bw:
                bw, best = w, r
    return best if bw > 0 else None


def _shape_partition(retrieved, corpus, _params):
    groups = defaultdict(list)
    for r in retrieved:
        k = corpus.full_key(r)
        if k is not None:
            groups[k].append(r)
    out, i = {}, 0
    for _k, rs in groups.items():
        if len(rs) < 2:
            continue
        anchor = rs[0]
        keep = sorted(x for x in rs if corpus.corroborate(anchor, x))
        if len(keep) >= 2:
            out[f"G{i}"] = keep
            i += 1
    return out


def _shape_false_merge(_retrieved, corpus, params):
    a = corpus.find(params["nom_a"], params["prenom_a"])
    b = corpus.find(params["nom_b"], params["prenom_b"])
    if not a or not b:
        return []
    a, b = a[0], b[0]
    ka = corpus.full_key(a)
    if ka is not None and ka == corpus.full_key(b) and corpus.corroborate(a, b):
        return sorted([a, b])
    return []


def _shape_records(rows, retrieved, corpus, params, ref_query):
    """record_fields: PAR-01 (parents), MIG-04 (trajectory), UNANS-REG (regiment)."""
    target = corpus.find(params.get("nom", ""), params.get("prenom")) if params.get("nom") else retrieved
    if ref_query == "RQ-UNANS-REG":
        out = []
        for row in rows:
            reg = _field(row, "regiment", "reg.nom")
            if reg:
                out.append({"rid": (target[0] if target else None), "regiment": reg})
        return out  # empty list = abstained (the correct answer under MASKED)
    if ref_query == "RQ-PAR-01":
        if not target:
            return []
        for row in rows:
            # the catalogue query returns collect({role,prenom,nom}) AS parents
            for v in row.values():
                if isinstance(v, list) and v and isinstance(v[0], dict) and "role" in v[0]:
                    pere = mere_nom = mere_pre = ""
                    for d in v:
                        role = (d.get("role") or "").lower()
                        if "father" in role or "pere" in role:
                            pere = d.get("prenom") or ""
                        elif "mother" in role or "mere" in role:
                            mere_pre = d.get("prenom") or ""
                            mere_nom = d.get("nom") or ""
                    return [{"rid": target[0], "pere_prenom": pere,
                             "mere_nom": mere_nom, "mere_prenom": mere_pre}]
            pp = _field(row, "pere_prenom", "pere")
            if pp is not None:
                return [{"rid": target[0], "pere_prenom": pp or "",
                         "mere_nom": _field(row, "mere_nom") or "",
                         "mere_prenom": _field(row, "mere_prenom") or ""}]
        return UNPARSEABLE  # query returned no parent columns
    if ref_query == "RQ-MIG-04":
        if not target:
            return []
        for row in rows:
            bd = _field(row, "naissance_depart", "birth_depart", "b.depart")
            dd = _field(row, "deces_depart", "death_depart", "d.depart")
            if bd is not None or dd is not None:
                return [{"rid": target[0], "birth_departement": bd or "",
                         "enrolement_annee": _field(row, "enrol") or "",
                         "death_departement": dd or ""}]
        return UNPARSEABLE
    return UNPARSEABLE


def _shape_disambig(rows, retrieved, corpus):
    return [{"rid": r, "matricule": corpus.g(r, "matricule"),
             "compagnie": corpus.g(r, "compagnie"),
             "naissance_lieu": corpus.g(r, "naissance_lieu"),
             "naissance_departement": corpus.g(r, "naissance_departement")}
            for r in sorted(set(retrieved))]


# --------------------------------------------------------------------------- #
# dispatch                                                                     #
# --------------------------------------------------------------------------- #

def shape(rows, result_kind, params, corpus, ref_query):
    """Return (prediction, retrieved_rids). prediction None => unparseable."""
    from .engines import _extract_count, _rows_to_rids
    rids, _ = _rows_to_rids(rows, corpus)
    p = params or {}

    if result_kind in ("rid_set", "rag_target"):
        return rids, rids
    if result_kind == "count":
        return {"count": _extract_count(rows, rids)}, rids
    if result_kind == "histogram":
        if "region" in p:  # Q-MIG-TOPO: count from a region
            depts = {norm(d) for d in corpus.topo.departments_for(p["region"])}
            n = sum(1 for r in rids if norm(corpus.g(r, "naissance_departement")) in depts)
            return {"count": n}, rids
        return (_parse_label_counts(rows) or _hist_from_rids(corpus, rids)), rids
    if result_kind == "histogram_pair":
        keys = [p.get("cie1"), p.get("cie2")]
        # best effort: bucket retrieved rids by their (token-resolved) company
        out = {}
        for cie in keys:
            comp_rids = [r for r in rids if r in set(corpus.company_rids(cie))]
            out[cie] = _hist_from_rids(corpus, comp_rids)
        return out, rids
    if result_kind == "aggregate":
        region = p.get("region")
        return (_parse_mean(rows) or _region_mean_from_rids(corpus, rids, region)), rids
    if result_kind == "aggregate_pair":
        out = {}
        for rk in (p.get("region_1"), p.get("region_2")):
            out[rk] = _region_mean_from_rids(corpus, rids, rk)
        return out, rids
    if result_kind == "linkage":
        cand = _candidate_rids(rows, corpus)
        return _shape_linkage(cand, corpus, p), sorted(cand)
    if result_kind == "partition":
        return _shape_partition(rids, corpus, p), rids
    if result_kind == "false_merge":
        return _shape_false_merge(rids, corpus, p), rids
    if result_kind == "record_fields":
        return _shape_records(rows, rids, corpus, p, ref_query), rids
    if result_kind == "disambiguation":
        return _shape_disambig(rows, rids, corpus), rids
    return None, rids
