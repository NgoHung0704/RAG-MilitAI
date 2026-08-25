---
title: MilitAI
emoji: 🎖️
colorFrom: indigo
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: RAG + knowledge graph over French military archives
---

# MilitAI — Space deployment

Hybrid query platform for French military records from the Ancien Régime:
RAG over a vector store, parameterized Cypher templates, and NL2Cypher, with a
synthetic validation corpus and an evaluation scorecard.

This Space packages the whole system — Streamlit plus **three Neo4j instances**
— into the single container Spaces allows. The databases listen on loopback
only (bolt 7687 / 7688 / 7689) and are never exposed; only Streamlit is.

Everything is **pre-seeded at image build time**: the Neo4j stores are restored
from offline dumps and the Chroma vector store is copied in. The container
therefore performs no ingestion at startup (`MILITAI_AUTOINGEST=off`) — a
restart costs only the JVM boot, which matters because Spaces discards anything
written to disk between restarts.

## Required secrets

Set these in **Settings → Variables and secrets**:

| Secret | Used by |
|---|---|
| `DEEPSEEK_API_KEY` | NL2Cypher generation and RAG answer synthesis |
| `OPENROUTER_API_KEY` | only the offline eval judge — not needed to run the demo |

Without `DEEPSEEK_API_KEY` the Template, Explore/Atlas, Showcase and Validation
Report tabs still work; RAG and NL2Cypher will not.

## Notes

- On free CPU hardware the Space sleeps when idle; the first request after a
  sleep pays a cold start of roughly one to two minutes while the three JVMs
  come up. Wake it before a live demo.
- Source of truth for the code is the GitHub repository; this Space is built
  from an assembled snapshot (`deploy/hf/assemble.sh`).
