"""
Engine registry — the systems under test, behind one interface.

An engine maps a question (NL text or bound ``ref_query``+``params``) to a
prediction in the catalogue's ``result_kind`` shape, for a given condition
(COMPLETE / MASKED). The runner scores that prediction against the oracle gold.

Engines:
  - ``reference`` — the executable catalogue (``reference.py``). Always available;
    it *is* the oracle, so it is the deterministic 100%-correct baseline and the
    gold producer. Its only sub-1.0 scores come from intrinsic MASKED degradation.
  - ``template`` / ``nl2cypher`` / ``rag`` — the live MilitAI modes. They require
    a Neo4j instance loaded with the corpus for that condition (and, for the LLM
    modes, a DeepSeek key). When the stack is unreachable they report
    ``available() == False`` and the runner skips them with a clear note rather
    than failing the run.

Live row -> result_kind reconciliation: Neo4j rows are matched back to corpus
``rid``s by (nom, prenom, matricule) so set/count metrics apply. Aggregate /
partition / linkage kinds need bespoke live extraction and are reported as
``unsupported`` for live engines until that is wired (tracked for the infra-up
pass).
"""

from __future__ import annotations

from .reference import Corpus, execute
from .text import norm


class EngineUnavailable(RuntimeError):
    """Raised by an engine whose backing stack is not reachable."""


class Engine:
    name = "base"
    # result_kinds this engine can produce; None = all.
    supports = None

    def available(self) -> bool:
        return True

    def can_do(self, result_kind: str) -> bool:
        return self.supports is None or result_kind in self.supports

    def predict(self, question: dict, condition: str, corpora: dict):
        """Return (result_kind, prediction, info). Raise EngineUnavailable if down."""
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# reference engine = the oracle                                               #
# --------------------------------------------------------------------------- #

class ReferenceEngine(Engine):
    name = "reference"

    def predict(self, question, condition, corpora):
        corpus = corpora[condition]
        kind, val = execute(question["ref_query"], corpus, question.get("params") or {})
        return kind, val, {}


# --------------------------------------------------------------------------- #
# live engines (Neo4j / DeepSeek)                                             #
# --------------------------------------------------------------------------- #

def _rid_index(corpus: Corpus):
    """Build lookup keys from the corpus for reconciling live rows to rids."""
    by_matricule, by_name = {}, {}
    for rid in corpus.rids:
        mat = corpus.g(rid, "matricule")
        if mat:
            by_matricule.setdefault(str(mat), rid)
        key = (norm(corpus.g(rid, "nom")), norm(corpus.g(rid, "prenom")))
        by_name.setdefault(key, []).append(rid)
    return by_matricule, by_name


def _row_get(row, col):
    """Fetch a column from a live row by bare or `s.`/prefixed alias."""
    if col in row:
        return row[col]
    for k, v in row.items():
        if k.lower().endswith("." + col) or k.lower() == col:
            return v
    return None


def _disambiguate(row, cand, corpus):
    """Among homonym candidates, pick the one whose secondary fields match the
    row (birth year/place, regiment, surnom, company). Unique match or None."""
    matches = []
    for rid in cand:
        ok = True
        for col, field in (("naissance_annee", "naissance_annee"),
                           ("naissance_lieu", "naissance_lieu"),
                           ("regiment", "regiment"), ("surnom", "surnom"),
                           ("compagnie", "compagnie"), ("matricule", "matricule")):
            val = _row_get(row, col)
            if val in (None, ""):
                continue
            if norm(str(val)) != norm(corpus.g(rid, field)):
                ok = False
                break
        if ok:
            matches.append(rid)
    return matches[0] if len(matches) == 1 else None


def _rows_to_rids(rows, corpus: Corpus):
    """Best-effort: map returned rows to corpus rids by matricule, then name,
    then (for homonyms) by secondary fields."""
    by_matricule, by_name = _rid_index(corpus)
    rids, unmatched = set(), 0
    for row in rows:
        mat = row.get("matricule") or row.get("s.matricule")
        if mat is not None and str(mat) in by_matricule:
            rids.add(by_matricule[str(mat)])
            continue
        nom = row.get("nom") or row.get("s.nom")
        prenom = row.get("prenom") or row.get("s.prenom")
        cand = by_name.get((norm(nom), norm(prenom)), []) if nom else []
        if len(cand) == 1:
            rids.add(cand[0])
        elif len(cand) > 1:
            chosen = _disambiguate(row, cand, corpus)
            if chosen is not None:
                rids.add(chosen)
            else:
                unmatched += 1
        else:
            unmatched += 1
    return sorted(rids), unmatched


def _extract_count(rows, rids):
    """A 'how many' query may return a scalar count or the soldier rows."""
    for row in rows:
        for k, v in row.items():
            if isinstance(v, (int, float)) and any(t in k.lower() for t in ("count", "n", "total")):
                return int(v)
    if len(rows) == 1 and len(rows[0]) == 1:
        (v,) = rows[0].values()
        if isinstance(v, (int, float)):
            return int(v)
    return len(rids)


class _Neo4jLiveEngine(Engine):
    """Shared plumbing for the Neo4j-backed live engines.

    Neo4j Community has one database, so conditions are evaluated one at a time:
    the runner re-ingests the right condition before calling, and ``drivers`` maps
    both conditions to the same live driver.
    """
    name = "neo4j-live"
    supports = None  # all kinds, via the shaping layer (None pred => unparseable)

    def __init__(self, drivers: dict | None = None):
        self.drivers = drivers or {}

    def available(self):
        return bool(self.drivers)

    def _session_run(self, cypher, condition, params=None):
        driver = self.drivers.get(condition)
        if driver is None:
            raise EngineUnavailable(f"no Neo4j driver for {condition}")
        with driver.session() as session:
            return [dict(rec) for rec in session.run(cypher, **(params or {}))]

    def _cypher_and_params(self, question):
        """Return (cypher, params) to execute. Raise EngineUnavailable to skip."""
        raise NotImplementedError

    def predict(self, question, condition, corpora):
        from .shaping import shape
        if not self.available():
            raise EngineUnavailable(f"{self.name}: Neo4j not reachable")
        cypher, params = self._cypher_and_params(question)
        rows = self._session_run(cypher, condition, params)
        corpus = corpora[condition]
        rq, qparams = question["ref_query"], question.get("params") or {}
        kind, _gold = execute(rq, corpus, qparams)  # oracle kind so scoring lines up
        pred, retrieved = shape(rows, kind, qparams, corpus, rq)
        return kind, pred, {"cypher": cypher, "n_rows": len(rows), "retrieved_rids": retrieved}


# ref_query -> (app template id, params adapter). Only the reference queries an
# app template actually covers are mapped; the rest report "no template" (a real
# coverage finding, since several questions list template mode but the shipping
# app has no matching template — e.g. company roster, enrol-range).
_TEMPLATE_MAP = {
    "RQ-NAME-01": ("by_surname", lambda p: {"nom": p["nom"]}),
    "RQ-NAME-02": ("by_full_name", lambda p: {"nom": p["nom"], "prenom": p["prenom"]}),
    "RQ-ENR-01": ("enlisted_year", lambda p: {"annee": int(p["year"])}),
    "RQ-BPL-01": ("from_department", lambda p: {"departement": p.get("dept") or p.get("region")}),
    "RQ-DTH-01": ("died_in_year", lambda p: {"annee": int(p["year"])}),
    "RQ-RNK-01": ("by_final_rank", lambda p: {"grade": p["rank"]}),
    "RQ-DES-01": ("deserted", lambda p: {}),
}


class TemplateEngine(_Neo4jLiveEngine):
    name = "template"

    def _cypher_and_params(self, question):
        rq = question["ref_query"]
        mapping = _TEMPLATE_MAP.get(rq)
        if mapping is None:
            raise EngineUnavailable(f"no app template for {rq}")
        from app.graph.templates import TEMPLATES_BY_ID
        template_id, adapt = mapping
        return TEMPLATES_BY_ID[template_id].cypher, adapt(question.get("params") or {})


class NL2CypherEngine(_Neo4jLiveEngine):
    name = "nl2cypher"

    def __init__(self, drivers=None, llm_client=None, lang="en"):
        super().__init__(drivers)
        self.client = llm_client
        self.lang = lang

    def available(self):
        return bool(self.drivers) and self.client is not None

    def _cypher_and_params(self, question):
        from app.graph.nl2cypher import nl_to_cypher
        return nl_to_cypher(question[self.lang], self.client), {}


class RAGEngine(Engine):
    name = "rag"
    # RAG answers are free text; scored on faithfulness/correctness vs the
    # record, handled by a separate LLM-judge pass (not the structured metrics).
    supports = {"rag_target"}

    def __init__(self, client=None, persist_dir=None, model=None, k=5):
        self.client = client
        self.persist_dir = persist_dir
        self.model = model
        self.k = k

    def available(self):
        return self.client is not None and self.persist_dir is not None

    def predict(self, question, condition, corpora):
        raise EngineUnavailable(
            "RAG scoring is an LLM-judge pass, run separately from the structured runner")


def build_registry(live=None):
    """Return the engines to run. ``live`` may inject configured live engines."""
    engines = [ReferenceEngine()]
    if live:
        engines.extend(live)
    return engines
