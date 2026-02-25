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
- Many fields are sparse — use OPTIONAL MATCH for relationships that may not exist.
- Use toLower() + CONTAINS for case-insensitive partial name matching.
- Place nodes are deduplicated on (lieu, departement, pays).

## Few-shot examples

User: Find all soldiers with the surname MARTIN
Cypher:
MATCH (s:Soldier)
WHERE toLower(s.nom) CONTAINS toLower('MARTIN')
RETURN s.nom, s.prenom, s.surnom, s.naissance_annee, s.regiment
ORDER BY s.nom

User: Which soldiers died in 1720?
Cypher:
MATCH (s:Soldier)-[r:DIED_IN]->(p:Place)
WHERE r.annee = 1720
RETURN s.nom, s.prenom, r.jour, r.mois, r.annee, p.lieu, p.pays
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
