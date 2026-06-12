"""
Value pools and gazetteer for the MilitAI synthetic validation corpus.

All values are authored (not LLM-generated). Surnames are ALL CAPS, place
names carry accents and historical spellings, departments use the (anachronistic
but schema-faithful) 1790 names that the real annotation schema also uses.

See specs/MilitAI_Synthetic_Validation_Spec.md §8 step 1.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

# Surnames, ALL CAPS as in the real registers. Includes multi-word particled
# names (DE BRIS) and an accented variant to exercise value traps.
SURNAMES = [
    # canonical catalogue names the reference questions bind to:
    "MARTIN", "DUPONT", "RENARD", "MOREAU", "ROUX", "BERNARD",
    "GIRARD", "BLANC", "LEROY", "FAURE", "CHALET",
    # background / value-trap surnames:
    "MOREL", "GUEGAN", "LE GOFF", "KERVELLA", "TANGUY", "RIOU",
    "PRIGENT", "JOURDAIN", "MASSON", "SCHMITT", "WEBER", "MULLER", "HOFFMANN",
    "BERTRAND", "FONTAINE", "ROUSSEL", "BARBIER", "RENAUD",
    "DELORME", "CHARPENTIER", "MARCHAND", "DUVAL", "LEMAIRE", "AUBERT",
    "GAILLARD", "PERRIN", "BRUN", "GARNIER", "CHEVALIER", "ROBIN",
    "MOULIN", "GUERIN", "MULOT", "POIRIER", "BRETON", "NORMAND",
    "DE BRIS", "DARDARE", "FABLET", "L'HOSTIS", "ROPARS",
]

# Surnames reserved for planted probes (vertical links, families, homonyms,
# single-record lookups). Background fillers draw from BG_SURNAMES, which excludes
# these, so accidental duplicates never pollute the reference questions' params.
RESERVED_SURNAMES = {
    "MARTIN", "DUPONT", "RENARD", "MOREAU", "ROUX", "BERNARD",
    "GIRARD", "BLANC", "LEROY", "FAURE", "CHALET",
}
BG_SURNAMES = [s for s in SURNAMES if s not in RESERVED_SURNAMES]

# First names from the period.
FIRST_NAMES = [
    "Jean", "Pierre", "Louis", "Guillaume", "Nicolas", "François", "Jacques",
    "Yves", "Mathurin", "Joseph", "Antoine", "René", "Michel", "Étienne",
    "Charles", "Gabriel", "Julien", "Mathieu", "Vincent", "Olivier",
    "Sébastien", "Bertrand", "Claude", "Honoré", "Corentin", "Hervé", "André",
]

FEMALE_NAMES = [
    "Marie", "Jeanne", "Anne", "Françoise", "Catherine", "Marguerite",
    "Louise", "Perrine", "Yvonne", "Renée", "Madeleine", "Barbe",
    "Geneviève", "Gabrielle", "Élisabeth",
]

# Maiden surnames for mothers (mere_nom), mixed case as recorded.
MAIDEN_NAMES = [
    "Le Bras", "Cariou", "Quéméner", "Salaün", "Hamon", "Thomas", "Lefebvre",
    "Petit", "Durand", "Schneider", "Becker", "Klein", "Henry", "Colin",
    "Picard", "Royer", "Adam", "Lambert", "Marie", "Caradec",
]

# surnom / dit-names distinct from nom.
SURNOMS = [
    "dit Saint-Jean", "dit La Rose", "dit Sans-Quartier", "dit La Fleur",
    "dit Brindamour", "dit La Tulipe", "dit Belhumeur", "dit Sans-Souci",
    "dit La Verdure", "dit Jolicoeur", "dit Saint-Amour", "dit Le Breton",
    "dit La Jeunesse", "dit Prêt-à-Boire", "dit La Montagne",
]

PROFESSIONS = [
    "laboureur", "tisserand", "maréchal-ferrant", "tailleur d'habits",
    "charpentier", "cordonnier", "meunier", "boulanger", "menuisier",
    "journalier", "vigneron", "tonnelier", "maçon",
]

# ---------------------------------------------------------------------------
# Military
# ---------------------------------------------------------------------------

# Gold companies are named unambiguously; tests filter on these exact strings.
GOLD_COMPANIES = {
    "A": "compagnie A",
    "B": "compagnie B",
    "C": "compagnie C",
    "D": "compagnie D",
}

# Background units — soldiers here never belong to a gold company.
BG_COMPANIES = [
    "compagnie de grenadiers", "compagnie colonelle", "compagnie de Bourbon",
    "compagnie de Picardie", "compagnie de Champagne", "compagnie de Navarre",
    "compagnie de la Reine", "compagnie Dauphine", "compagnie de Vermandois",
]

REGIMENTS = [
    "régiment de Picardie", "régiment de Navarre", "régiment de Champagne",
    "régiment du Roi", "régiment de Bourbon", "régiment de la Reine",
]

BATAILLONS = ["1er bataillon", "2e bataillon", "3e bataillon"]

# rank pool — note: no "colonel" / "capitaine", so rank queries for those are
# zero-result by construction.
RANKS = ["soldat", "caporal", "sergent", "fourrier", "tambour", "anspessade"]

# ---------------------------------------------------------------------------
# Gazetteer: department -> communes (+ region/province, jurisdiction, pays)
# ---------------------------------------------------------------------------

# region is the coarse migration/stature grain (province names).
DEPARTMENTS = {
    "Finistère":      {"region": "Bretagne",      "pays": "France",
                        "communes": ["Quimper", "Brest", "Landerneau", "Morlaix", "Quimperlé", "Le Faou"]},
    "Côtes-du-Nord":  {"region": "Bretagne",      "pays": "France",
                        "communes": ["Saint-Brieuc", "Dinan", "Lannion", "Guingamp"]},
    "Morbihan":       {"region": "Bretagne",      "pays": "France",
                        "communes": ["Vannes", "Lorient", "Auray", "Pontivy"]},
    "Bas-Rhin":       {"region": "Alsace",        "pays": "France",
                        "communes": ["Strasbourg", "Haguenau", "Saverne", "Sélestat"]},
    "Moselle":        {"region": "Lorraine",      "pays": "France",
                        "communes": ["Metz", "Thionville", "Sarreguemines", "Brieulles-sur-Meuse"]},
    "Meurthe":        {"region": "Lorraine",      "pays": "France",
                        "communes": ["Nancy", "Lunéville", "Toul", "Pont-à-Mousson"]},
    "Seine":          {"region": "Île-de-France", "pays": "France",
                        "communes": ["Paris", "Saint-Denis", "Vincennes"]},
    "Rhône":          {"region": "Lyonnais",      "pays": "France",
                        "communes": ["Lyon", "Villefranche"]},
    "Gironde":        {"region": "Guyenne",       "pays": "France",
                        "communes": ["Bordeaux", "Libourne"]},
    "Nord":           {"region": "Flandre",       "pays": "France",
                        "communes": ["Lille", "Douai", "Valenciennes"]},
    "Isère":          {"region": "Dauphiné",      "pays": "France",
                        "communes": ["Grenoble", "Vienne"]},
    "Puy-de-Dôme":    {"region": "Auvergne",      "pays": "France",
                        "communes": ["Clermont", "Riom", "Marcigny"]},
    "Eure":           {"region": "Normandie",     "pays": "France",
                        "communes": ["Évreux", "Bernay", "Les Andelys"]},
    # Corse: planted-only origin (naissance_pieve); not used by gold companies.
    "Corse":          {"region": "Corse",          "pays": "Corse",
                        "communes": ["Corte", "Cervione", "Ajaccio", "Bastia"]},
}

# Background-only departments (for marginal mass / negatives); not used by any
# gold company.
BG_DEPARTMENTS = ["Eure", "Puy-de-Dôme", "Isère", "Nord", "Gironde"]

JURIDICTIONS = [
    "subdélégation", "sénéchaussée", "bailliage", "élection", "prévôté",
]

MONTHS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
    "août", "septembre", "octobre", "novembre", "décembre",
]


def jurisdiction_for(commune: str, idx: int) -> str:
    """Deterministic jurisdiction string derived from a commune name."""
    return f"{JURIDICTIONS[idx % len(JURIDICTIONS)]} de {commune}"


def region_of(department: str) -> str:
    return DEPARTMENTS[department]["region"]


def pays_of(department: str) -> str:
    return DEPARTMENTS[department]["pays"]
