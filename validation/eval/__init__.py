"""MilitAI synthetic-corpus evaluation harness.

Consumes the generator outputs (``corpus/questions.jsonl`` + ``corpus/gold/``)
and the reference-query catalogue, executes each query mode against the corpus,
and scores the result against gold per ``result_kind``.

Modules:
  - ``metrics``   — scoring functions, one per ``result_kind``.
  - ``reference`` — the deterministic pandas engine implementing the RQ-* catalogue.
  - ``engines``   — the live engine adapters (template / nl2cypher / rag) + registry.
  - ``runner``    — orchestration, degradation analysis, reporting.
"""
