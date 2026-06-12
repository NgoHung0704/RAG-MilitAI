"""
The executable Reference Query Catalogue — the evaluation **oracle**.

Each ``RQ-*`` from ``MilitAI_Reference_Query_Catalogue.md`` is implemented here
as a deterministic pandas computation over the COMPLETE / MASKED corpus, with
its catalogue post-processing (corroboration, soft-gap weight, height
conversion) and the catalogue matching rules (``norm()`` folding + toponym
Layer-M resolution). Running a query yields ``(result_kind, gold_value)``.

This is the catalogue's §10 protocol made executable: the gold *is* the result
of executing the reference query on the corpus. The runner uses it both to
produce gold and as the deterministic ``reference`` engine (a 100%-correct
baseline whose only departure from 1.0 is intrinsic data degradation under
MASKED).

Binding: ``params`` come verbatim from ``questions.jsonl`` (``{"nom":"MARTIN"}``,
``{"cie":"Cie_A"}``, ``{"region":"Bretagne"}``, …).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from .text import norm
from .toponym import ToponymResolver

# Height unit constants (pied du roi), per catalogue §7.
PIED_CM, POUCE_CM, LIGNE_CM = 32.484, 2.707, 0.2256


# --------------------------------------------------------------------------- #
# soft generational-gap weight w(g)  (validation spec §5.2)                    #
# --------------------------------------------------------------------------- #

def w_gap(g: int) -> float:
    if g is None or g < 16:
        return 0.0
    if g < 25:
        return round((g - 16) / 9, 3)
    if g <= 45:
        return 1.0
    if g <= 58:
        return round(1 - (g - 45) / 13, 3)
    return 0.0


def _company_token(label: str) -> str:
    """Trailing alphanumeric run, normalised — folds 'Cie_A' / 'compagnie A'."""
    toks = re.findall(r"[A-Za-z0-9]+", str(label or ""))
    return norm(toks[-1]) if toks else ""


def _as_int(v):
    try:
        return int(str(v).strip())
    except (ValueError, TypeError):
        return None


class Corpus:
    """A condition's records (COMPLETE or MASKED) + catalogue helpers.

    ``df`` is row-indexed by ``rid`` (0-based position, identical across
    conditions). All cells are strings; '' denotes an absent value.
    """

    def __init__(self, df):
        self.df = df.reset_index(drop=True)
        self.rids = list(range(len(self.df)))
        self.topo = ToponymResolver(self.df)
        # department -> region, derived from the corpus (decoupled gazetteer)
        self._dept_region: dict[str, str] = {}
        if "naissance_region" in self.df.columns:
            for dept, reg in zip(self.df["naissance_departement"], self.df["naissance_region"]):
                if dept and reg:
                    self._dept_region.setdefault(norm(dept), reg)

    # -- cell access ------------------------------------------------------- #
    def g(self, rid, col):
        return self.df.at[rid, col] if col in self.df.columns else ""

    def present(self, rid, col):
        return bool(self.g(rid, col))

    def rows(self):
        for rid in self.rids:
            yield rid

    # -- company ----------------------------------------------------------- #
    def company_rids(self, cie):
        tok = _company_token(cie)
        out = []
        for rid in self.rids:
            c = self.g(rid, "compagnie")
            if c and (norm(c) == norm(cie) or _company_token(c) == tok):
                out.append(rid)
        return out

    # -- geography --------------------------------------------------------- #
    def region_of(self, rid):
        reg = self.g(rid, "naissance_region")
        if reg:
            return reg
        return self._dept_region.get(norm(self.g(rid, "naissance_departement")), "")

    # -- height ------------------------------------------------------------ #
    def height_cm(self, rid):
        tm = self.g(rid, "taille_metre")
        if tm:
            try:
                return float(str(tm).replace(",", ".")) * 100.0
            except ValueError:
                pass
        pied = _as_int(self.g(rid, "pied"))
        if pied is not None:
            pouce = _as_int(self.g(rid, "pouce")) or 0
            ligne = _as_int(self.g(rid, "ligne")) or 0
            return pied * PIED_CM + pouce * POUCE_CM + ligne * LIGNE_CM
        return None

    def has_height(self, rid):
        return bool(self.g(rid, "taille_metre")) or bool(self.g(rid, "pied"))

    # -- genealogy keys ---------------------------------------------------- #
    def full_key(self, rid):
        """4-field parent identity, or None if any field missing."""
        nom = self.g(rid, "nom")
        pp = self.g(rid, "pere_prenom")
        mn = self.g(rid, "mere_nom")
        mp = self.g(rid, "mere_prenom")
        if nom and pp and mn and mp:
            return (norm(nom), norm(pp), norm(mn), norm(mp))
        return None

    def corroborate(self, a, b):
        """Null-tolerant: birthplace agree-or-missing AND |year gap| <=25-or-missing."""
        la, lb = self.g(a, "naissance_lieu"), self.g(b, "naissance_lieu")
        bp_ok = (not la) or (not lb) or (norm(la) == norm(lb))
        ya, yb = _as_int(self.g(a, "naissance_annee")), _as_int(self.g(b, "naissance_annee"))
        yr_ok = (ya is None) or (yb is None) or abs(ya - yb) <= 25
        return bp_ok and yr_ok

    def find(self, nom, prenom=None):
        """rids whose (nom[, prenom]) match under norm()."""
        out = []
        for rid in self.rids:
            if norm(self.g(rid, "nom")) != norm(nom):
                continue
            if prenom is not None and norm(self.g(rid, "prenom")) != norm(prenom):
                continue
            out.append(rid)
        return out

    def siblings(self, nom, prenom, father_only=False, include_self=False):
        """Corroborated sibling set of (nom, prenom)."""
        anchors = self.find(nom, prenom)
        if not anchors:
            return []
        a = anchors[0]
        if father_only:
            key = (norm(self.g(a, "nom")), norm(self.g(a, "pere_prenom")))
            if not all(key):
                return []
            cand = [r for r in self.rids
                    if (norm(self.g(r, "nom")), norm(self.g(r, "pere_prenom"))) == key]
        else:
            key = self.full_key(a)
            if key is None:
                return []
            cand = [r for r in self.rids if self.full_key(r) == key]
        keep = [r for r in cand if self.corroborate(a, r)]
        if not include_self:
            keep = [r for r in keep if r != a]
        return sorted(keep)


# --------------------------------------------------------------------------- #
# RQ handlers: (corpus, params) -> (result_kind, gold)                         #
# --------------------------------------------------------------------------- #

def _rid_set(corpus, pred):
    return "rid_set", sorted(r for r in corpus.rids if pred(r))


def rq_name_01(c, p):
    return _rid_set(c, lambda r: norm(c.g(r, "nom")) == norm(p["nom"]))


def rq_name_02(c, p):
    return _rid_set(c, lambda r: norm(c.g(r, "nom")) == norm(p["nom"])
                    and norm(c.g(r, "prenom")) == norm(p["prenom"]))


def rq_name_03(c, p):
    frag = norm(p["frag"])
    return _rid_set(c, lambda r: frag in norm(c.g(r, "nom")))


def rq_comp_01(c, p):
    rids = set(c.company_rids(p["cie"]))
    if "region" in p:  # Q-MIG-TOPO style count (kept under RQ-COMP-01? no) -> handled in MIG
        pass
    return "rid_set", sorted(rids)


def rq_comp_02(c, p):
    m = str(p["matricule"])
    return _rid_set(c, lambda r: c.present(r, "matricule") and str(c.g(r, "matricule")) == m)


def rq_enr_01(c, p):
    y = int(p["year"])
    return _rid_set(c, lambda r: _as_int(c.g(r, "enrolement_annee")) == y)


def rq_enr_02(c, p):
    lo, hi = int(p["min"]), int(p["max"])
    def pred(r):
        v = _as_int(c.g(r, "enrolement_annee"))
        return v is not None and lo <= v <= hi
    return _rid_set(c, pred)


def rq_bpl_01(c, p):
    label = p.get("dept") or p.get("region")
    depts = {norm(d) for d in c.topo.departments_for(label)}
    def pred(r):
        d = c.g(r, "naissance_departement")
        return bool(d) and norm(d) in depts
    return _rid_set(c, pred)


def rq_rec_01(c, p):
    return "rag_target", sorted(c.find(p["nom"], p["prenom"]))


def rq_dth_01(c, p):
    y = int(p["year"])
    return _rid_set(c, lambda r: _as_int(c.g(r, "deces_annee")) == y)


def rq_rnk_01(c, p):
    rank = norm(p["rank"])
    return _rid_set(c, lambda r: c.present(r, "grade_final") and rank in norm(c.g(r, "grade_final")))


def rq_par_01(c, p):
    out = []
    for r in c.find(p["nom"], p["prenom"]):
        out.append({"rid": r, "pere_prenom": c.g(r, "pere_prenom"),
                    "mere_nom": c.g(r, "mere_nom"), "mere_prenom": c.g(r, "mere_prenom")})
    return "record_fields", out


def rq_sib_01(c, p):
    return "rid_set", c.siblings(p["nom"], p["prenom"])


def rq_sib_02(c, p):
    """Family clusters within a company: full-key groups (size>=2, corroborated)."""
    members = c.company_rids(p["cie"])
    groups = defaultdict(list)
    for r in members:
        k = c.full_key(r)
        if k is not None:
            groups[k].append(r)
    clusters = {}
    i = 0
    for k, rs in groups.items():
        if len(rs) < 2:
            continue
        anchor = rs[0]
        keep = sorted(r for r in rs if c.corroborate(anchor, r))
        if len(keep) >= 2:
            clusters[f"G{i}"] = keep
            i += 1
    return "partition", clusters


def rq_sib_03(c, p):
    """Decoy: are A and B brothers? gold = [a,b] iff truly siblings else []."""
    a = c.find(p["nom_a"], p["prenom_a"])
    b = c.find(p["nom_b"], p["prenom_b"])
    if not a or not b:
        return "false_merge", []
    a, b = a[0], b[0]
    sib = set(c.siblings(p["nom_a"], p["prenom_a"], include_self=True))
    return "false_merge", (sorted([a, b]) if b in sib and a in sib else [])


def rq_sib_04(c, p):
    """Partial-key / father-only fallback (lower confidence)."""
    return "rid_set", c.siblings(p["nom"], p["prenom"], father_only=True)


def _linkage(c, p):
    sons = c.find(p["nom"], p["prenom"])
    if not sons:
        return "linkage", None
    s = sons[0]
    son_birth = _as_int(c.g(s, "naissance_annee"))
    pere = c.g(s, "pere_prenom")
    best, best_w = None, 0.0
    for r in c.rids:
        if r == s:
            continue
        if norm(c.g(r, "nom")) == norm(c.g(s, "nom")) and pere and norm(c.g(r, "prenom")) == norm(pere):
            fb = _as_int(c.g(r, "naissance_annee"))
            gap = (son_birth - fb) if (son_birth is not None and fb is not None) else None
            w = w_gap(gap)
            if w > best_w:
                best_w, best = w, r
    return "linkage", (best if best_w > 0 else None)


def _histogram(c, rids, col="naissance_departement"):
    return dict(sorted(Counter(c.g(r, col) for r in rids if c.g(r, col)).items()))


def rq_mig_01(c, p):
    members = c.company_rids(p["cie"])
    if "region" in p:  # Q-MIG-TOPO: count company soldiers from a region
        depts = {norm(d) for d in c.topo.departments_for(p["region"])}
        n = sum(1 for r in members
                if c.g(r, "naissance_departement") and norm(c.g(r, "naissance_departement")) in depts)
        return "count", {"count": n}
    return "histogram", _histogram(c, members)


def rq_mig_02(c, p):
    y = int(p["year"])
    members = [r for r in c.rids if _as_int(c.g(r, "enrolement_annee")) == y]
    return "histogram", _histogram(c, members)


def rq_mig_03(c, p):
    return "histogram_pair", {
        p["cie1"]: _histogram(c, c.company_rids(p["cie1"])),
        p["cie2"]: _histogram(c, c.company_rids(p["cie2"])),
    }


def rq_mig_04(c, p):
    out = []
    for r in c.find(p["nom"], p["prenom"]):
        out.append({"rid": r,
                    "birth_departement": c.g(r, "naissance_departement"),
                    "enrolement_annee": c.g(r, "enrolement_annee"),
                    "death_departement": c.g(r, "deces_departement")})
    return "record_fields", out


def _region_mean(c, region):
    target = norm(region)
    # accept region name directly, or via department membership of the region
    depts = {norm(d) for d in c.topo.departments_for(region)}
    vals = []
    for r in c.rids:
        if not c.has_height(r):
            continue
        rreg = c.region_of(r)
        rdept = c.g(r, "naissance_departement")
        if norm(rreg) == target or (rdept and norm(rdept) in depts):
            cm = c.height_cm(r)
            if cm is not None:
                vals.append(cm)
    if not vals:
        return {"n": 0, "mean_cm": None}
    return {"n": len(vals), "mean_cm": round(sum(vals) / len(vals), 1)}


def rq_anth_01(c, p):
    return "aggregate", _region_mean(c, p["region"])


def rq_anth_02(c, p):
    thr = float(p["threshold_cm"])
    def pred(r):
        if not c.has_height(r):
            return False
        cm = c.height_cm(r)
        return cm is not None and cm > thr
    return _rid_set(c, pred)


def rq_anth_03(c, p):
    return "aggregate_pair", {
        p["region_1"]: _region_mean(c, p["region_1"]),
        p["region_2"]: _region_mean(c, p["region_2"]),
    }


def rq_unans_reg(c, p):
    out = []
    for r in c.find(p["nom"], p["prenom"]):
        if c.present(r, "regiment"):
            out.append({"rid": r, "regiment": c.g(r, "regiment")})
    return "record_fields", out


def rq_zero(c, p):
    y = int(p["year"])
    return _rid_set(c, lambda r: _as_int(c.g(r, "deces_annee")) == y)


def rq_dis(c, p):
    out = []
    for r in c.find(p["nom"], p["prenom"]):
        out.append({"rid": r, "matricule": c.g(r, "matricule"),
                    "compagnie": c.g(r, "compagnie"),
                    "naissance_lieu": c.g(r, "naissance_lieu"),
                    "naissance_departement": c.g(r, "naissance_departement")})
    return "disambiguation", out


def rq_agg_count(c, p):
    return "count", {"count": len(c.company_rids(p["cie"]))}


def rq_multi(c, p):
    anchors = c.find(p["nom"], p["prenom"])
    if not anchors:
        return "rid_set", []
    a = anchors[0]
    place = c.g(a, "naissance_lieu")
    if not place:
        return "rid_set", []
    pn = norm(place)
    return "rid_set", sorted(r for r in c.rids
                             if r != a and c.g(r, "naissance_lieu") and norm(c.g(r, "naissance_lieu")) == pn)


def rq_des_01(c, p):
    return _rid_set(c, lambda r: norm(c.g(r, "desertion")) == "oui")


REGISTRY = {
    "RQ-NAME-01": rq_name_01, "RQ-NAME-02": rq_name_02, "RQ-NAME-03": rq_name_03,
    "RQ-COMP-01": rq_comp_01, "RQ-COMP-02": rq_comp_02,
    "RQ-ENR-01": rq_enr_01, "RQ-ENR-02": rq_enr_02,
    "RQ-BPL-01": rq_bpl_01, "RQ-REC-01": rq_rec_01,
    "RQ-DTH-01": rq_dth_01, "RQ-RNK-01": rq_rnk_01, "RQ-PAR-01": rq_par_01,
    "RQ-SIB-01": rq_sib_01, "RQ-SIB-02": rq_sib_02, "RQ-SIB-03": rq_sib_03,
    "RQ-SIB-04": rq_sib_04,
    "RQ-VERT-01": _linkage, "RQ-VERT-02": _linkage, "RQ-VERT-03": _linkage,
    "RQ-VERT-04": _linkage, "RQ-VERT-05": _linkage,
    "RQ-MIG-01": rq_mig_01, "RQ-MIG-02": rq_mig_02, "RQ-MIG-03": rq_mig_03,
    "RQ-MIG-04": rq_mig_04,
    "RQ-ANTH-01": rq_anth_01, "RQ-ANTH-02": rq_anth_02, "RQ-ANTH-03": rq_anth_03,
    "RQ-UNANS-REG": rq_unans_reg, "RQ-ZERO": rq_zero, "RQ-DIS": rq_dis,
    "RQ-AGG-COUNT": rq_agg_count, "RQ-MULTI": rq_multi, "RQ-DES-01": rq_des_01,
}


def execute(ref_query: str, corpus: Corpus, params: dict):
    """Run a reference query. Returns (result_kind, gold_value).

    Unknown ref_query -> (None, None) so the runner can flag coverage gaps
    rather than crash."""
    fn = REGISTRY.get(ref_query)
    if fn is None:
        return None, None
    return fn(corpus, params or {})
