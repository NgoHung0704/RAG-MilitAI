"""
Showcase example registry loader (Demo Interface Spec v0.2 §6).

Joins the curated ``showcase.yaml`` to the synthetic corpus' ``questions.jsonl``
(FR/EN text, ref_query) and its precomputed gold (``gold/answers.json``: per
question a ``result_kind`` plus the ``complete`` / ``masked`` oracle values).

Pure Python — no Streamlit — so it is unit-testable on its own.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

import app.config as config


@dataclass
class ShowcaseExample:
    # presentation metadata (from showcase.yaml)
    id: str
    use_case: str
    title: str
    question_id: str
    run_modes: list[str] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)
    compare: bool = False
    reveal_gold: bool = True
    tour_order: int = 0
    narrative: str = ""
    # joined data
    question: dict = field(default_factory=dict)
    gold: dict = field(default_factory=dict)

    # -- convenience accessors -------------------------------------------- #
    @property
    def ref_query(self) -> str:
        return self.question.get("ref_query", "")

    @property
    def result_kind(self) -> str:
        return self.gold.get("result_kind", "")

    def text(self, lang: str = "en") -> str:
        return self.question.get(lang, self.question.get("en", ""))

    def gold_for(self, condition: str):
        """``condition`` is 'complete' or 'masked'."""
        return self.gold.get(condition)

    @property
    def has_gold(self) -> bool:
        return bool(self.gold) and self.result_kind != ""


# --------------------------------------------------------------------------- #
# loaders                                                                      #
# --------------------------------------------------------------------------- #

def load_questions(path: str | Path) -> dict[str, dict]:
    """Read a JSONL question file into a dict keyed by question id."""
    out: dict[str, dict] = {}
    p = Path(path)
    if not p.exists():
        return out
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            q = json.loads(line)
            out[q["id"]] = q
    return out


def load_gold(path: str | Path) -> dict[str, dict]:
    """Read ``answers.json`` (gold keyed by question id)."""
    p = Path(path)
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as fh:
        return json.load(fh)


def _default_showcase_yaml() -> Path:
    return config.PROJECT_ROOT / "showcase.yaml"


def load_showcase(
    yaml_path: str | Path | None = None,
    questions_path: str | Path | None = None,
    gold_path: str | Path | None = None,
) -> list[ShowcaseExample]:
    """Load and join the showcase registry.

    Defaults resolve from the synthetic dataset registry entry. Examples whose
    ``question_id`` is absent from the questions file are skipped (so a partial
    registry never crashes the booth).
    """
    yaml_path = Path(yaml_path or _default_showcase_yaml())
    synth = config.get_dataset("synth_complete")
    questions = load_questions(questions_path or synth["questions"])
    gold = load_gold(gold_path or synth["gold"])

    if not yaml_path.exists():
        return []

    with yaml_path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or []

    examples: list[ShowcaseExample] = []
    for entry in raw:
        qid = entry.get("question_id")
        if not qid or qid not in questions:
            continue
        examples.append(
            ShowcaseExample(
                id=entry["id"],
                use_case=entry.get("use_case", "other"),
                title=entry.get("title", qid),
                question_id=qid,
                run_modes=list(entry.get("run_modes", [])),
                datasets=list(entry.get("datasets", config.SYNTH_DATASETS)),
                compare=bool(entry.get("compare", False)),
                reveal_gold=bool(entry.get("reveal_gold", True)),
                tour_order=int(entry.get("tour_order", 0)),
                narrative=entry.get("narrative", ""),
                question=questions.get(qid, {}),
                gold=gold.get(qid, {}),
            )
        )
    examples.sort(key=lambda e: e.tour_order)
    return examples


def group_by_use_case(examples: list[ShowcaseExample]) -> dict[str, list[ShowcaseExample]]:
    """Gallery grouping — preserves tour order within each use case."""
    groups: dict[str, list[ShowcaseExample]] = {}
    for ex in examples:
        groups.setdefault(ex.use_case, []).append(ex)
    return groups
