"""The proposal roles must be told the ontology's qualifier vocabulary.

``prompts/kpi.v1.txt`` mentioned qualifiers nowhere, yet every ontology metric
now requires specific ones to produce a comparability key. ``build_comparability_key``
fails closed on a missing required qualifier, so a live model — told nothing —
would fail comparability on essentially every row. The suite was green only
because the deterministic mock injects currency/construction/scope itself.

The fix generates the vocabulary from ``load_saas_metrics()`` at role-load time
instead of hand-writing it into the ``.txt``, so it cannot drift from the data
file. These tests pin exactly that: the *data* is the source, not the prompt.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from fel_ontology import load_saas_metrics
from fel_workers.extraction.roles.base import (
    ROLE_SPECS,
    load_role_specs,
    render_qualifier_vocabulary,
)
from fel_workers.extraction.types import Role

PROMPTS = (
    Path(__file__).resolve().parents[3]
    / "workers"
    / "src"
    / "fel_workers"
    / "extraction"
    / "prompts"
)

VOCABULARY_ROLES = (Role.KPI, Role.GUIDANCE)


@pytest.fixture(scope="module")
def ontology():  # type: ignore[no-untyped-def]
    return load_saas_metrics()


@pytest.mark.parametrize("role", VOCABULARY_ROLES)
def test_instructions_name_every_metric_and_its_required_qualifiers(role, ontology) -> None:  # type: ignore[no-untyped-def]
    instructions = ROLE_SPECS[role].instructions
    for metric in ontology.metrics:
        assert metric.id in instructions, metric.id
        for qualifier in metric.required_qualifiers:
            assert qualifier in instructions, f"{metric.id}.{qualifier}"


@pytest.mark.parametrize("role", VOCABULARY_ROLES)
def test_instructions_say_omit_rather_than_invent(role) -> None:  # type: ignore[no-untyped-def]
    """A missing qualifier is a resolvable blocker; a fabricated one is silent corruption."""
    instructions = ROLE_SPECS[role].instructions.lower()
    assert "omit" in instructions
    assert "never invent" in instructions
    assert "issuer" in instructions


def test_vocabulary_is_generated_not_written_into_the_prompt_file() -> None:
    """The .txt must stay free of per-metric detail, or it can drift from the data.

    Only the generic pointer lines may mention qualifiers; the metric ids and
    qualifier names must come from the ontology at load time.
    """
    tokens = (
        "arr",
        "mrr",
        "crpo",
        "deferred_rev",
        "sub_gm",
        "construction",
        "horizon_months",
        "label_family",
        "tag_family",
    )
    for name in ("kpi.v1.txt", "guidance.v1.txt", "revenue_driver.v1.txt"):
        text = (PROMPTS / name).read_text(encoding="utf-8")
        for token in tokens:
            assert not re.search(rf"\b{re.escape(token)}\b", text), f"{name} hand-writes {token}"


def test_vocabulary_tracks_a_doctored_ontology(tmp_path: Path) -> None:
    """Change the data file and the rendered vocabulary changes with it.

    This is the anti-drift property: nothing is restated in the prompt, so an
    ontology edit cannot leave the instructions stale.
    """
    packaged = (
        Path(__file__).resolve().parents[3]
        / "packages"
        / "ontology"
        / "fel_ontology"
        / "data"
        / "saas-metrics.v1.json"
    )
    doc = json.loads(packaged.read_text(encoding="utf-8"))
    for metric in doc["metrics"]:
        if metric["id"] == "seats":
            metric["required_qualifiers"] = ["seat_scope", "invented_qualifier"]
            metric["comparability_key_fields"] = ["metric_id", "seat_scope"]
    target = tmp_path / "saas-metrics.v1.json"
    target.write_text(json.dumps(doc), encoding="utf-8")

    rendered = render_qualifier_vocabulary(load_saas_metrics(path=str(target)))
    assert "invented_qualifier" in rendered
    assert "invented_qualifier" not in render_qualifier_vocabulary()


def test_vocabulary_pins_the_ontology_content_hash(ontology) -> None:  # type: ignore[no-untyped-def]
    assert ontology.content_hash in render_qualifier_vocabulary()


@pytest.mark.parametrize("role", VOCABULARY_ROLES)
def test_instructions_hash_moves_with_the_ontology(role, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """DELIBERATE side effect: the step request hash tracks the qualifier vocabulary.

    Output computed under one qualifier vocabulary must not be restored from a
    checkpoint keyed as if it had been computed under another, so the hash
    moving here is the correct behaviour, not a regression.
    """
    baseline = ROLE_SPECS[role].instructions_hash()
    assert baseline == load_role_specs()[role].instructions_hash()

    ontology_only = render_qualifier_vocabulary()
    assert ontology_only in ROLE_SPECS[role].instructions
    prompt_only = ROLE_SPECS[role].instructions.replace(ontology_only, "")
    # The prompt file alone hashes differently from prompt + vocabulary.
    bare = "sha256:" + hashlib.sha256(prompt_only.encode()).hexdigest()
    assert bare != baseline


def test_driver_mapper_is_not_given_the_metric_vocabulary() -> None:
    """revenue_driver.metric_id is a driver category, not an ontology metric.

    Handing it the metric list would invite it to write an ontology metric id
    into a field that is not one, which is worse than the omission.
    """
    instructions = ROLE_SPECS[Role.DRIVER_MAPPER].instructions
    assert "horizon_months" not in instructions
    assert "QUALIFIERS" not in instructions


def test_classifier_and_fact_table_are_unchanged() -> None:
    for role, name in (
        (Role.CLASSIFIER, "classifier.v1.txt"),
        (Role.FACT_CANDIDATES, "fact_table.v1.txt"),
    ):
        assert ROLE_SPECS[role].instructions == (PROMPTS / name).read_text(encoding="utf-8")
