# MilitAI — French Military Records Explorer

> Une plateforme hybride pour explorer les archives militaires de l'Ancien Régime (XVIIᵉ–XVIIIᵉ siècle) grâce à l'IA.

MilitAI combine **trois modes de requête** dans une seule interface Streamlit :

| Mode | Description | Backend |
|------|-------------|---------|
| **RAG** | Recherche sémantique + réponse générée | ChromaDB + DeepSeek |
| **Template** | Requêtes Cypher paramétrées prêtes à l'emploi | Neo4j |
| **NL2Cypher** | Question en langage naturel → Cypher → résultats | Neo4j + DeepSeek |

Projet réalisé en partenariat avec le laboratoire **LIRIS** (INSA Lyon, 4IF AGIR).

---

## Table des matières

- [Démarrage rapide](#démarrage-rapide)
- [Prérequis](#prérequis)
- [Installation pas à pas](#installation-pas-à-pas)
- [Utilisation quotidienne](#utilisation-quotidienne)
- [Architecture](#architecture)
- [Structure du projet](#structure-du-projet)
- [Commandes Make](#commandes-make)
- [Dépannage](#dépannage)

---

## Démarrage rapide

Pour les impatients, **6 commandes** suffisent :

```bash
make install      # 1. Dépendances Python
make env          # 2. Copier .env.example → .env  (puis éditer .env)
make neo4j-up     # 3. Démarrer Neo4j (Docker)
make ingest       # 4. Charger le dataset complet dans Neo4j (~13k soldats)
make ingest-rag   # 5. Construire ChromaDB (embeddings)
make run          # 6. Lancer Streamlit → http://localhost:8501
```

---

## Prérequis

- **Python 3.11+**
- **Docker Desktop 4.0+** (pour Neo4j)
- **GNU Make** (déjà présent sur Linux/macOS ; sur Windows : via Git Bash, WSL ou `choco install make`)
- **Clé API DeepSeek** → [platform.deepseek.com](https://platform.deepseek.com/) (pour les modes RAG et NL2Cypher)

---

## Installation pas à pas

### 1. Dépendances Python

```bash
make install
```

Installe `pandas`, `streamlit`, `neo4j`, `chromadb`, `sentence-transformers`, `openai`, etc.

### 2. Configuration de l'environnement

```bash
make env
```

Cela copie `.env.example` en `.env`. **Ouvrez `.env` et renseignez** :

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=neo4jpassword      # ← doit correspondre au container Neo4j
DEEPSEEK_API_KEY=sk-...           # ← votre clé DeepSeek
```

### 3. Démarrer Neo4j

```bash
make neo4j-up
```

Lance Neo4j dans un container Docker :
- **Bolt** (pour l'app) : `bolt://localhost:7687`
- **UI Browser** : http://localhost:7474

### 4. Charger les données dans Neo4j

```bash
make ingest
```

Charge le dataset complet (~13 000 soldats) — quelques minutes.

### 5. Construire la base vectorielle (RAG)

```bash
make ingest-rag
```

Embed chaque soldat dans ChromaDB (stockée dans `data/chroma_db/`).

> ⚠️ Le premier lancement télécharge le modèle `all-MiniLM-L6-v2` (~90 MB).

### 6. Lancer l'application

```bash
make run
```

Ouvrez http://localhost:8501 dans votre navigateur.

---

## Utilisation quotidienne

Une fois tout installé, seules 3 commandes suffisent au quotidien :

```bash
make neo4j-up   # démarrer Neo4j
make run        # lancer Streamlit
make neo4j-down # arrêter Neo4j en fin de session
```

### Modes de requête dans l'UI

| Mode | Question-type | Exemple |
|------|---------------|---------|
| **RAG** | Questions ouvertes en français | *"Parle-moi des soldats nés à Paris"* |
| **Template** | Recherche structurée par paramètres | Surname = `MARTIN` |
| **NL2Cypher** | Question précise sur le graphe | *"Qui est né à Paris et mort en 1719 ?"* |

---

## Architecture

```
                 ┌─────────────────────────┐
                 │      Streamlit UI       │
                 │       app/main.py       │
                 └────────────┬────────────┘
                              │
              ┌───────────────┴───────────────┐
              │                               │
   ┌──────────▼──────────┐       ┌────────────▼────────┐
   │   Graph Pipeline    │       │    RAG Pipeline     │
   │    app/graph/*      │       │      app/rag/*      │
   │ (templates + NL2Cy) │       │  (retriever + LLM)  │
   └──────────┬──────────┘       └────────────┬────────┘
              │                               │
   ┌──────────▼──────────┐       ┌────────────▼────────┐
   │       Neo4j         │       │      ChromaDB       │
   │  graphe de soldats  │       │   vecteurs locaux   │
   └─────────────────────┘       └─────────────────────┘

         Source commune : data/*.csv (Mémoire des Hommes / SHDGR)
```

---

## Structure du projet

```
RAG-MilitAI/
├── app/
│   ├── main.py              # Entrée Streamlit
│   ├── config.py            # Chargement .env
│   ├── graph/               # Neo4j : connexion, templates, NL2Cypher
│   ├── rag/                 # RAG : ingestion, retriever, chain
│   └── ui/                  # Panels Streamlit (un par mode)
├── data/
│   ├── sample_of_data.csv                # 4 lignes — dev/tests
│   ├── full_unified_annotations.csv      # Dataset complet
│   ├── full_unified_annotations_patch.csv # Dataset corrigé (à utiliser)
│   └── chroma_db/                        # Vector store (gitignored)
├── scripts/
│   ├── ingest_neo4j.py      # CSV → Neo4j
│   └── ingest_rag.py        # CSV → ChromaDB
├── docs/                    # Diagrammes, figures
├── Dockerfile
├── docker-compose.yml
├── Makefile                 # Workflow en 6 étapes
├── requirements.txt
└── .env.example
```

---

## Commandes Make

Liste complète avec `make` (ou `make help`).

### Installation (à faire une fois)

| Commande | Action |
|----------|--------|
| `make install` | Installer les dépendances Python |
| `make env` | Créer `.env` depuis `.env.example` |

### Neo4j

| Commande | Action |
|----------|--------|
| `make neo4j-up` | Démarrer Neo4j (Docker) |
| `make neo4j-down` | Arrêter Neo4j |
| `make neo4j-shell` | Ouvrir `cypher-shell` |

### Ingestion

| Commande | Action |
|----------|--------|
| `make ingest` | Charger le dataset complet dans Neo4j |
| `make ingest-rag` | Construire ChromaDB depuis le dataset complet |

### Application

| Commande | Action |
|----------|--------|
| `make run` | Lancer Streamlit sur http://localhost:8501 |

### Workflow full-Docker (alternatif)

Pour tout containeriser (app + Neo4j) :

| Commande | Action |
|----------|--------|
| `make docker-build` | Construire l'image de l'app |
| `make docker-up` | Démarrer Neo4j + Streamlit |
| `make docker-down` | Arrêter tous les services |
| `make docker-logs` | Suivre les logs |
| `make docker-clean` | Tout arrêter + supprimer les volumes |

---

## Dépannage

### ❌ `neo4j.exceptions.AuthError: Unauthorized`

Le mot de passe Neo4j dans `.env` ne correspond pas à celui du container.

**Solution** :
```bash
make docker-clean    # supprime les volumes Neo4j
make neo4j-up        # recrée avec le mot de passe défini dans docker-compose.yml
```

Ou ajustez `NEO4J_PASSWORD` dans `.env` pour qu'il corresponde.

### ❌ `ModuleNotFoundError: No module named 'app'` (au lancement Streamlit)

Le projet n'est pas dans le `PYTHONPATH`. Lancez toujours depuis la racine :
```bash
streamlit run app/main.py    # ✓ OK
```
Pas depuis un sous-dossier.

### ❌ ChromaDB : `KeyError: '_type'`

Version incompatible du store ChromaDB.

**Solution** :
```bash
rm -rf data/chroma_db
make ingest-rag
```

### ❌ NL2Cypher renvoie 0 résultats ou trop de résultats

- Vérifiez que Neo4j contient bien le dataset complet : `make ingest`
- Redémarrez Streamlit pour recharger le prompt système : `Ctrl+C` puis `make run`
- Ouvrez "Generated Cypher" dans l'UI pour inspecter la requête produite

### ℹ️ Voir les logs Neo4j

```bash
make docker-logs
```

---

## Notes techniques

- **Données** : les CSV contiennent ~75 colonnes par soldat (identité, naissance, décès, régiment, famille, archive source). Beaucoup de champs sont vides — l'ingestion ignore les valeurs NaN/null.
- **Déduplication des lieux** : les nœuds `Place` sont fusionnés sur la clé `(lieu, departement, pays)` via `MERGE`.
- **Dates** : stockées comme propriétés entières séparées (`jour`, `mois`, `annee`) — pas de type `date` (trop de dates partielles).
- **Modèle LLM** : `deepseek-chat` (via SDK OpenAI compatible).
- **Modèle d'embedding** : `all-MiniLM-L6-v2` (local, sentence-transformers).

---

## Attribution des données

Les registres proviennent des archives militaires françaises :
**Mémoire des Hommes** — [memoiredeshommes.sga.defense.gouv.fr](https://www.memoiredeshommes.sga.defense.gouv.fr/)
*Service Historique de la Défense (SHDGR / Ministère des Armées).*

Ce dépôt fournit l'outillage de traitement et de requête ; l'interprétation historique reste de la responsabilité du chercheur.

---

## Équipe

Étudiants 4IF INSA Lyon, en collaboration avec **Diana Nurbakova** et **Killian Barrere** (laboratoire LIRIS).
