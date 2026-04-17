COMPOSE ?= docker compose

.DEFAULT_GOAL := help

.PHONY: help check-docker build up down restart logs ps app-shell neo4j-shell ingest-neo4j-sample ingest-neo4j-full ingest-rag-sample ingest-rag-full clean

help:
	@echo "MilitAI - development commands"
	@echo ""
	@echo "Infrastructure"
	@echo "  make build                Build Docker image for app"
	@echo "  make up                   Start Neo4j + Streamlit in background"
	@echo "  make down                 Stop all services"
	@echo "  make restart              Restart all services"
	@echo "  make logs                 Follow container logs"
	@echo "  make ps                   Show service status"
	@echo ""
	@echo "Ingestion"
	@echo "  make ingest-neo4j-sample  Ingest sample CSV into Neo4j"
	@echo "  make ingest-neo4j-full    Ingest full CSV into Neo4j"
	@echo "  make ingest-rag-sample    Build ChromaDB from sample CSV"
	@echo "  make ingest-rag-full      Build ChromaDB from full CSV"
	@echo ""
	@echo "Utilities"
	@echo "  make app-shell            Open shell in app container"
	@echo "  make neo4j-shell          Open cypher-shell in Neo4j container"
	@echo "  make clean                Stop and remove all volumes"

check-docker:
	@$(COMPOSE) version > /dev/null

build: check-docker
	@$(COMPOSE) build app

up: check-docker
	@$(COMPOSE) up -d neo4j app

down:
	@$(COMPOSE) down

restart: down up

logs:
	@$(COMPOSE) logs -f --tail=200

ps:
	@$(COMPOSE) ps

app-shell:
	@$(COMPOSE) run --rm app /bin/bash

neo4j-shell:
	@$(COMPOSE) exec neo4j cypher-shell -u $${NEO4J_USER:-neo4j} -p $${NEO4J_PASSWORD:-neo4jpassword}

ingest-neo4j-sample: up
	@$(COMPOSE) run --rm app python scripts/ingest_neo4j.py --sample

ingest-neo4j-full: up
	@$(COMPOSE) run --rm app python scripts/ingest_neo4j.py

ingest-rag-sample: up
	@$(COMPOSE) run --rm app python scripts/ingest_rag.py --sample

ingest-rag-full: up
	@$(COMPOSE) run --rm app python scripts/ingest_rag.py

clean:
	@$(COMPOSE) down -v --remove-orphans