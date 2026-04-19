COMPOSE ?= docker compose
PYTHON  ?= python

.DEFAULT_GOAL := help

.PHONY: help \
        install env \
        neo4j-up neo4j-down neo4j-shell \
        ingest ingest-rag \
        run \
        docker-build docker-up docker-down docker-restart docker-logs docker-ps docker-app-shell docker-clean \
        check-docker

# ============================================================
# HELP — affiché par défaut : `make`
# ============================================================
help:
	@echo ""
	@echo "  MilitAI — commandes de développement"
	@echo "  ===================================="
	@echo ""
	@echo "  PREMIERE UTILISATION (à faire dans l'ordre)"
	@echo "  -------------------------------------------"
	@echo "  1) make install       Installer les dépendances Python"
	@echo "  2) make env           Copier .env.example vers .env"
	@echo "  3) make neo4j-up      Démarrer Neo4j (container Docker)"
	@echo "  4) make ingest        Charger le dataset complet dans Neo4j"
	@echo "  5) make ingest-rag    Construire ChromaDB (dataset complet)"
	@echo "  6) make run           Lancer l'app Streamlit"
	@echo ""
	@echo "  UTILISATION QUOTIDIENNE"
	@echo "  -----------------------"
	@echo "  make neo4j-up         Démarrer Neo4j"
	@echo "  make run              Lancer Streamlit (app/main.py)"
	@echo "  make neo4j-down       Arrêter Neo4j"
	@echo ""
	@echo "  OUTILS"
	@echo "  ------"
	@echo "  make neo4j-shell      Ouvrir cypher-shell (CLI Neo4j)"
	@echo ""
	@echo "  DOCKER — stack complète (alternative : tout containerisé)"
	@echo "  ---------------------------------------------------------"
	@echo "  make docker-build     Construire l'image Docker de l'app"
	@echo "  make docker-up        Démarrer Neo4j + Streamlit via Docker"
	@echo "  make docker-down      Arrêter tous les services Docker"
	@echo "  make docker-restart   Redémarrer tous les services"
	@echo "  make docker-logs      Suivre les logs des containers"
	@echo "  make docker-ps        Voir le statut des services"
	@echo "  make docker-app-shell Shell dans le container app"
	@echo "  make docker-clean     Arrêt + suppression des volumes"
	@echo ""

# ============================================================
# ÉTAPES — workflow local (Python + Neo4j en Docker)
# ============================================================

# 1) Installer les dépendances Python
install:
	@echo ">> Installation des dépendances Python…"
	$(PYTHON) -m pip install -r requirements.txt

# 2) Copier le template d'environnement
env:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo ">> .env créé depuis .env.example — éditez-le pour y mettre vos clés."; \
	else \
		echo ">> .env existe déjà — aucune action."; \
	fi

# 3) Démarrer uniquement Neo4j (en Docker)
neo4j-up: check-docker
	@echo ">> Démarrage de Neo4j…"
	@$(COMPOSE) up -d neo4j
	@echo ">> Neo4j prêt sur bolt://localhost:7687  —  UI sur http://localhost:7474"

neo4j-down:
	@$(COMPOSE) stop neo4j

# 4) Ingérer le CSV complet dans Neo4j
ingest: neo4j-up
	@echo ">> Ingestion du dataset complet dans Neo4j…"
	$(PYTHON) scripts/ingest_neo4j.py

# 5) Construire ChromaDB pour le RAG (dataset complet)
ingest-rag:
	@echo ">> Construction de ChromaDB (dataset complet)…"
	$(PYTHON) scripts/ingest_rag.py

# 6) Lancer Streamlit
run:
	@echo ">> Lancement de Streamlit sur http://localhost:8501 …"
	streamlit run app/main.py

# ============================================================
# OUTILS
# ============================================================
neo4j-shell:
	@$(COMPOSE) exec neo4j cypher-shell -u $${NEO4J_USER:-neo4j} -p $${NEO4J_PASSWORD:-neo4jpassword}

# ============================================================
# DOCKER — stack complète (app + neo4j containerisés)
# ============================================================
check-docker:
	@$(COMPOSE) version > /dev/null

docker-build: check-docker
	@$(COMPOSE) build app

docker-up: check-docker
	@$(COMPOSE) up -d neo4j app

docker-down:
	@$(COMPOSE) down

docker-restart: docker-down docker-up

docker-logs:
	@$(COMPOSE) logs -f --tail=200

docker-ps:
	@$(COMPOSE) ps

docker-app-shell:
	@$(COMPOSE) run --rm app /bin/bash

docker-clean:
	@$(COMPOSE) down -v --remove-orphans
