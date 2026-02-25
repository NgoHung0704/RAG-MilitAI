"""
Parameterized Cypher query templates.

Each Template has:
  - id: machine-readable key
  - name: human label shown in UI
  - description: what the query returns
  - params: list of ParamDef (drives UI form rendering)
  - cypher: Cypher string with $param placeholders
"""

from __future__ import annotations

from dataclasses import dataclass, field

import neo4j


@dataclass
class ParamDef:
    name: str           # matches $param in Cypher
    type: str           # "str" or "int"
    label: str          # UI label
    placeholder: str = ""


@dataclass
class Template:
    id: str
    name: str
    description: str
    params: list[ParamDef]
    cypher: str


TEMPLATES: list[Template] = [
    Template(
        id="by_surname",
        name="Find by surname",
        description="Returns all soldiers whose surname contains the search term (case-insensitive).",
        params=[ParamDef("nom", "str", "Surname", "e.g. CHALET")],
        cypher="""
MATCH (s:Soldier)
WHERE toLower(s.nom) CONTAINS toLower($nom)
RETURN s.nom AS nom, s.prenom AS prenom, s.surnom AS surnom,
       s.naissance_annee AS naissance_annee, s.naissance_lieu AS naissance_lieu,
       s.regiment AS regiment, s.matricule AS matricule
ORDER BY s.nom, s.prenom
        """.strip(),
    ),
    Template(
        id="by_full_name",
        name="Find by first name + surname",
        description="Returns soldiers matching both first name and surname (case-insensitive partial match).",
        params=[
            ParamDef("prenom", "str", "First name", "e.g. Jean"),
            ParamDef("nom", "str", "Surname", "e.g. CHALET"),
        ],
        cypher="""
MATCH (s:Soldier)
WHERE toLower(s.nom) CONTAINS toLower($nom)
  AND toLower(s.prenom) CONTAINS toLower($prenom)
RETURN s.nom AS nom, s.prenom AS prenom, s.surnom AS surnom,
       s.naissance_annee AS naissance_annee, s.naissance_lieu AS naissance_lieu,
       s.regiment AS regiment, s.matricule AS matricule
ORDER BY s.nom, s.prenom
        """.strip(),
    ),
    Template(
        id="died_in_year",
        name="Died in year",
        description="Returns all soldiers who died in the given year.",
        params=[ParamDef("annee", "int", "Year of death", "e.g. 1721")],
        cypher="""
MATCH (s:Soldier)-[r:DIED_IN]->(p:Place)
WHERE r.annee = $annee
RETURN s.nom AS nom, s.prenom AS prenom, s.surnom AS surnom,
       r.jour AS deces_jour, r.mois AS deces_mois, r.annee AS deces_annee,
       p.lieu AS deces_lieu, p.pays AS deces_pays
ORDER BY s.nom
        """.strip(),
    ),
    Template(
        id="born_in_place",
        name="Born in place",
        description="Returns soldiers born in a place matching the given name (case-insensitive partial match).",
        params=[ParamDef("lieu", "str", "Place name", "e.g. Paris")],
        cypher="""
MATCH (s:Soldier)-[:BORN_IN]->(p:Place)
WHERE toLower(p.lieu) CONTAINS toLower($lieu)
RETURN s.nom AS nom, s.prenom AS prenom, s.surnom AS surnom,
       p.lieu AS naissance_lieu, p.departement AS naissance_departement, p.pays AS naissance_pays,
       s.regiment AS regiment
ORDER BY s.nom
        """.strip(),
    ),
    Template(
        id="in_regiment",
        name="All soldiers in regiment",
        description="Returns all soldiers who served in a regiment matching the given name.",
        params=[ParamDef("regiment", "str", "Regiment name", "e.g. grenadiers")],
        cypher="""
MATCH (s:Soldier)-[:SERVED_IN]->(r:Regiment)
WHERE toLower(r.nom) CONTAINS toLower($regiment)
RETURN s.nom AS nom, s.prenom AS prenom, s.surnom AS surnom,
       r.nom AS regiment, s.matricule AS matricule,
       s.grade_final AS grade_final
ORDER BY s.nom
        """.strip(),
    ),
    Template(
        id="deserted",
        name="Soldiers who deserted",
        description="Returns all soldiers recorded as having deserted.",
        params=[],
        cypher="""
MATCH (s:Soldier)-[r:DESERTED_FROM]->(reg:Regiment)
RETURN s.nom AS nom, s.prenom AS prenom, s.surnom AS surnom,
       reg.nom AS regiment,
       r.jour AS desertion_jour, r.mois AS desertion_mois, r.annee AS desertion_annee
ORDER BY s.nom
        """.strip(),
    ),
    Template(
        id="died_year_surname",
        name="Died in year with surname",
        description="Returns soldiers with the given surname who died in the given year.",
        params=[
            ParamDef("annee", "int", "Year of death", "e.g. 1721"),
            ParamDef("nom", "str", "Surname", "e.g. CHALET"),
        ],
        cypher="""
MATCH (s:Soldier)-[r:DIED_IN]->(p:Place)
WHERE r.annee = $annee
  AND toLower(s.nom) CONTAINS toLower($nom)
RETURN s.nom AS nom, s.prenom AS prenom, s.surnom AS surnom,
       r.jour AS deces_jour, r.mois AS deces_mois, r.annee AS deces_annee,
       p.lieu AS deces_lieu
ORDER BY s.nom
        """.strip(),
    ),
    Template(
        id="born_year_range",
        name="Born in year range",
        description="Returns soldiers born between annee_min and annee_max (inclusive).",
        params=[
            ParamDef("annee_min", "int", "Birth year from", "e.g. 1650"),
            ParamDef("annee_max", "int", "Birth year to", "e.g. 1700"),
        ],
        cypher="""
MATCH (s:Soldier)
WHERE s.naissance_annee >= $annee_min
  AND s.naissance_annee <= $annee_max
RETURN s.nom AS nom, s.prenom AS prenom, s.surnom AS surnom,
       s.naissance_annee AS naissance_annee, s.naissance_lieu AS naissance_lieu,
       s.regiment AS regiment
ORDER BY s.naissance_annee, s.nom
        """.strip(),
    ),
    Template(
        id="by_final_rank",
        name="By final rank",
        description="Returns soldiers whose final rank matches the given name.",
        params=[ParamDef("grade", "str", "Rank name", "e.g. sergent")],
        cypher="""
MATCH (s:Soldier)-[h:HELD_RANK]->(r:Rank)
WHERE h.order = 'final'
  AND toLower(r.nom) CONTAINS toLower($grade)
RETURN s.nom AS nom, s.prenom AS prenom, s.surnom AS surnom,
       r.nom AS grade_final, s.regiment AS regiment
ORDER BY s.nom
        """.strip(),
    ),
    Template(
        id="soldier_parents",
        name="Soldier with parents",
        description="Returns a soldier and their recorded parents, filtered by surname.",
        params=[ParamDef("nom", "str", "Soldier surname", "e.g. CHALET")],
        cypher="""
MATCH (s:Soldier)
WHERE toLower(s.nom) CONTAINS toLower($nom)
OPTIONAL MATCH (s)-[c:CHILD_OF]->(p:Person)
RETURN s.nom AS nom, s.prenom AS prenom,
       collect({role: c.role, prenom: p.prenom, nom: p.nom, profession: p.profession}) AS parents
ORDER BY s.nom
        """.strip(),
    ),
    Template(
        id="enlisted_year",
        name="Enlisted in year",
        description="Returns soldiers who enlisted in the given year.",
        params=[ParamDef("annee", "int", "Enlistment year", "e.g. 1715")],
        cypher="""
MATCH (s:Soldier)
WHERE s.enrolement_annee = $annee
RETURN s.nom AS nom, s.prenom AS prenom, s.surnom AS surnom,
       s.enrolement_annee AS enrolement_annee,
       s.regiment AS regiment, s.grade_final AS grade_final
ORDER BY s.nom
        """.strip(),
    ),
    Template(
        id="from_department",
        name="From department",
        description="Returns soldiers born or domiciled in the given department (partial match).",
        params=[ParamDef("departement", "str", "Department", "e.g. Paris")],
        cypher="""
MATCH (s:Soldier)
WHERE toLower(s.naissance_departement) CONTAINS toLower($departement)
   OR toLower(s.domicile_departement)  CONTAINS toLower($departement)
RETURN s.nom AS nom, s.prenom AS prenom, s.surnom AS surnom,
       s.naissance_departement AS naissance_departement,
       s.domicile_departement  AS domicile_departement,
       s.regiment AS regiment
ORDER BY s.nom
        """.strip(),
    ),
]

# Lookup by template id
TEMPLATES_BY_ID: dict[str, Template] = {t.id: t for t in TEMPLATES}


def run_template(
    driver: neo4j.Driver,
    template: Template,
    params: dict,
) -> list[dict]:
    """Execute a template against Neo4j and return rows as plain dicts."""
    with driver.session() as session:
        result = session.run(template.cypher, **params)
        return [dict(record) for record in result]
