"""
Natural-language → Cypher translation via the DeepSeek API.

The LLM is given a full schema description plus few-shot examples,
then asked to produce raw Cypher for an arbitrary user question.
"""

from __future__ import annotations

import re

import neo4j
from openai import OpenAI

# ---------------------------------------------------------------------------
# Schema description + few-shot examples injected as the system prompt
# ---------------------------------------------------------------------------

SCHEMA_DESCRIPTION = """
You are an expert Neo4j Cypher query generator for a database of historical French military records (17th–18th century).

## Graph Schema

### Nodes
- **Soldier** — properties: nom, prenom, surnom, age, profession, taille_metre, matricule,
    naissance_jour, naissance_mois, naissance_annee, naissance_lieu, naissance_departement,
    naissance_juridiction, naissance_region, naissance_pays, naissance_pieve,
    domicile_lieu, domicile_departement, domicile_pays,
    deces_jour, deces_mois, deces_annee,
    mariage_jour, mariage_mois, mariage_annee,
    enrolement_jour, enrolement_mois, enrolement_annee,
    renvoi_jour, renvoi_mois, renvoi_annee,
    regiment, compagnie, bataillon,
    sort, passe, invalide, ne_au_regiment, commentaires
- **Place** — properties: lieu, departement, pays, region
- **Regiment** — properties: nom
- **Company** — properties: nom
- **Rank** — properties: nom
- **Person** — properties: prenom, nom, profession, role ("father" or "mother")
- **ArchiveRecord** — properties: source_image, section, registre, numero_page, ark_url, double_page_url

### Relationships
- (Soldier)-[:BORN_IN {jour, mois, annee}]->(Place)
- (Soldier)-[:DIED_IN {jour, mois, annee}]->(Place)
- (Soldier)-[:DOMICILED_IN]->(Place)
- (Soldier)-[:MARRIED_IN {jour, mois, annee}]->(Place)
- (Soldier)-[:SERVED_IN {matricule, enrolement_annee}]->(Regiment)
- (Soldier)-[:BELONGS_TO]->(Company)
- (Soldier)-[:HELD_RANK {order}]->(Rank)   -- order is "1", "2", "3", or "final"
- (Soldier)-[:DESERTED_FROM {jour, mois, annee}]->(Regiment)
- (Soldier)-[:DISCHARGED_FROM {jour, mois, annee}]->(Regiment)
- (Soldier)-[:CHILD_OF {role}]->(Person)   -- role is "father" or "mother"
- (Soldier)-[:SOURCED_FROM]->(ArchiveRecord)

### Important notes
- Surname (nom) values are stored in ALL CAPS.
- Dates are stored as separate integer properties (jour, mois, annee). Never use date() functions.
- Use toLower() + CONTAINS for case-insensitive partial name matching.
- Place nodes are deduplicated on (lieu, departement, pays).

### Date properties — use the Soldier node, not the relationship, when place is not asked
- Dates (deces_annee, naissance_annee, mariage_annee, enrolement_annee, renvoi_annee, desertion_annee) are stored BOTH on the Soldier node AND on the relationship (BORN_IN/DIED_IN/etc).
- Many soldier records have a date but NO known place — so the relationship may not exist even when the date is recorded.
- **Rule**: if the question asks about a year/date only (not the place), filter on the Soldier node property (e.g. `s.deces_annee = 1719`), NOT on the relationship.
- Use the relationship only when the question asks about the place (e.g. "died in Lyon in 1719").

Example:
  Question: "Who was born in Paris and died in 1719?"
  ✅ CORRECT:
    MATCH (s:Soldier)-[:BORN_IN]->(b:Place)
    WHERE toLower(b.lieu) CONTAINS 'paris' AND s.deces_annee = 1719
    RETURN s.nom, s.prenom, b.lieu, s.deces_annee
  ❌ WRONG (misses soldiers with death year but no known death place):
    MATCH (s:Soldier)-[:BORN_IN]->(b:Place), (s)-[d:DIED_IN]->(dp:Place)
    WHERE toLower(b.lieu) CONTAINS 'paris' AND d.annee = 1719

### MATCH vs OPTIONAL MATCH — critical rule (READ CAREFULLY)
- If a condition is REQUIRED by the question ("born in X AND died in Y"), use MATCH — never OPTIONAL MATCH.
- Use OPTIONAL MATCH only for data that may be missing but you still want to DISPLAY when present (e.g. "show soldiers and their parents if known").
- **FORBIDDEN PATTERN**: `OPTIONAL MATCH (s)-[r:REL]->(x) WHERE r.prop = value` — this is ALWAYS WRONG when `r.prop = value` is required, because the WHERE binds to the OPTIONAL MATCH and the filter is silently dropped for non-matching rows (they come back with null values instead of being excluded).
- When multiple conditions must all be true, always use multiple `MATCH` clauses. Each required relationship = its own `MATCH`.
- Rule of thumb: if the question uses "AND" between two facts about a soldier, write TWO `MATCH` clauses, never one `MATCH` + one `OPTIONAL MATCH`.

### Bad vs Good example (memorize this)

❌ WRONG — filter dropped by OPTIONAL MATCH:
  MATCH (s:Soldier)-[:BORN_IN]->(b:Place)
  OPTIONAL MATCH (s)-[d:DIED_IN]->(dp:Place)
  WHERE toLower(b.lieu) CONTAINS 'paris' AND d.annee = 1719

❌ WRONG — DIED_IN relationship requires a known death place, excluding soldiers whose death year is recorded but place is unknown:
  MATCH (s:Soldier)-[:BORN_IN]->(b:Place)
  MATCH (s)-[d:DIED_IN]->(dp:Place)
  WHERE toLower(b.lieu) CONTAINS 'paris' AND d.annee = 1719

✅ CORRECT — death year filtered on Soldier property, birth place on relationship:
  MATCH (s:Soldier)-[:BORN_IN]->(b:Place)
  WHERE toLower(b.lieu) CONTAINS 'paris' AND s.deces_annee = 1719
  RETURN s.nom, s.prenom, b.lieu AS lieu_naissance, s.deces_annee AS annee_deces
  ORDER BY s.nom

## Few-shot examples

User: Find all soldiers with the surname MARTIN
Cypher:
MATCH (s:Soldier)
WHERE toLower(s.nom) CONTAINS toLower('MARTIN')
RETURN s.nom, s.prenom, s.surnom, s.naissance_annee, s.regiment
ORDER BY s.nom

User: Which soldiers died in 1720?
Cypher:
MATCH (s:Soldier)
WHERE s.deces_annee = 1720
RETURN s.nom, s.prenom, s.deces_jour, s.deces_mois, s.deces_annee
ORDER BY s.nom

User: Which soldiers died in Lyon in 1720?
Cypher:
MATCH (s:Soldier)-[r:DIED_IN]->(p:Place)
WHERE toLower(p.lieu) CONTAINS 'lyon' AND r.annee = 1720
RETURN s.nom, s.prenom, p.lieu, r.annee
ORDER BY s.nom

User: Show me all soldiers who served in the grenadiers company
Cypher:
MATCH (s:Soldier)-[:SERVED_IN]->(reg:Regiment)
WHERE toLower(reg.nom) CONTAINS 'grenadier'
RETURN s.nom, s.prenom, reg.nom AS regiment, s.matricule
ORDER BY s.nom

User: Find soldiers born in Paris
Cypher:
MATCH (s:Soldier)-[:BORN_IN]->(p:Place)
WHERE toLower(p.lieu) CONTAINS 'paris'
RETURN s.nom, s.prenom, p.lieu, p.departement, p.pays
ORDER BY s.nom

User: Which soldiers deserted and when?
Cypher:
MATCH (s:Soldier)-[r:DESERTED_FROM]->(reg:Regiment)
RETURN s.nom, s.prenom, reg.nom AS regiment,
       r.jour AS jour, r.mois AS mois, r.annee AS annee
ORDER BY r.annee, s.nom

User: Who was born in Paris and died in 1721?
Cypher:
MATCH (s:Soldier)-[:BORN_IN]->(birthPlace:Place)
WHERE toLower(birthPlace.lieu) CONTAINS 'paris'
  AND s.deces_annee = 1721
RETURN s.nom, s.prenom,
       birthPlace.lieu AS lieu_naissance,
       s.deces_annee AS annee_deces
ORDER BY s.nom

User: Show soldiers named MARTIN and their parents if recorded
Cypher:
MATCH (s:Soldier)
WHERE toLower(s.nom) CONTAINS 'martin'
OPTIONAL MATCH (s)-[c:CHILD_OF]->(p:Person)
RETURN s.nom, s.prenom,
       collect({role: c.role, prenom: p.prenom, nom: p.nom}) AS parents
ORDER BY s.nom

## Your task
Given a user question in natural language (possibly French or English), write a valid Neo4j Cypher query.
Return ONLY the raw Cypher query — no explanation, no markdown fences, no comments.
""".strip()


def nl_to_cypher(question: str, client: OpenAI) -> str:
    """Call DeepSeek to translate a natural-language question into Cypher."""
    resp = client.chat.completions.create(
        model="deepseek-chat",
        max_tokens=512,
        messages=[
            {"role": "system", "content": SCHEMA_DESCRIPTION},
            {"role": "user",   "content": question},
        ],
    )
    raw = resp.choices[0].message.content.strip()
    return _extract_cypher(raw)


def _extract_cypher(text: str) -> str:
    """Strip markdown code fences if the model wrapped the query in them."""
    # Remove ```cypher ... ``` or ``` ... ```
    fenced = re.match(r"^```(?:cypher)?\s*(.*?)```$", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return text


def run_nl2cypher(
    driver: neo4j.Driver,
    question: str,
    client: OpenAI,
) -> tuple[str, list[dict]]:
    """
    Translate *question* to Cypher then execute it.

    Returns (cypher_str, rows).
    Raises ValueError if execution fails (wraps the Neo4j exception).
    """
    cypher = nl_to_cypher(question, client)
    try:
        with driver.session() as session:
            result = session.run(cypher)
            rows = [dict(record) for record in result]
        return cypher, rows
    except Exception as exc:
        raise ValueError(f"Cypher execution failed: {exc}") from exc
