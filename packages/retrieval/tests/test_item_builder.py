from __future__ import annotations

import hashlib
from typing import Any

from fel_retrieval import build_items

INDEX = "99999999-9999-4999-8999-999999999999"


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def mini_corpus(*, corrupt_passage_hash: bool = False) -> dict[str, Any]:
    canonical = (
        "ITEM 8. FINANCIAL STATEMENTS\n"
        "Revenue was $100 million in fiscal 2025.\n"
        "Cost of sales was $40 million.\n"
        "UNANCHORED_ROW_PLACEHOLDER"
    )
    revenue = "Revenue was $100 million in fiscal 2025."
    cost = "Cost of sales was $40 million."
    rev_start = canonical.index(revenue)
    rev_end = rev_start + len(revenue)
    cost_start = canonical.index(cost)
    cost_end = cost_start + len(cost)
    rev_hash = _sha(revenue)
    if corrupt_passage_hash:
        rev_hash = _sha("tampered")
    return {
        "entity_id": "11111111-1111-4111-8111-111111111111",
        "document_id": "22222222-2222-4222-8222-222222222222",
        "document_version_id": "33333333-3333-4333-8333-333333333333",
        "form": "10-K",
        "canonical_text": canonical,
        "source_spans": [
            {
                "id": "44444444-4444-4444-8444-444444444444",
                "section_id": "55555555-5555-4555-8555-555555555555",
                "start_char": rev_start,
                "end_char": rev_end,
                "text": revenue,
                "text_hash": rev_hash,
                "heading_path": ["ITEM 8", "FINANCIAL STATEMENTS"],
            },
            {
                "id": "66666666-6666-4666-8666-666666666666",
                "section_id": "55555555-5555-4555-8555-555555555555",
                "start_char": cost_start,
                "end_char": cost_end,
                "text": cost,
                "text_hash": _sha(cost),
                "heading_path": ["ITEM 8", "FINANCIAL STATEMENTS"],
            },
        ],
        "financial_facts": [
            {
                "id": "77777777-7777-4777-8777-777777777777",
                "source_span_id": "44444444-4444-4444-8444-444444444444",
                "period": "FY2025",
            }
        ],
        "tables": [
            {
                "id": "88888888-8888-4888-8888-888888888888",
                "section_id": "55555555-5555-4555-8555-555555555555",
                "heading_path": ["ITEM 8", "Tables"],
                "rows": [
                    {"source_span_id": "66666666-6666-4666-8666-666666666666"},
                    {"source_span_id": None},
                ],
            }
        ],
    }


def test_happy_path_kinds_and_anchors() -> None:
    result = build_items(mini_corpus(), index_version_id=INDEX)
    kinds = {item.kind for item in result.items}
    assert kinds == {"passage", "fact", "table_row"}
    # Two passages (revenue + cost spans), one fact, one anchored table row.
    assert result.counts["items"] == 4
    assert result.counts["passage"] == 2
    assert result.counts["fact"] == 1
    assert result.counts["table_row"] == 1
    assert result.counts["rejections"] == 1
    assert result.rejections[0].code == "UNANCHORED_TABLE_ROW"
    passage = next(i for i in result.items if i.kind == "passage")
    assert passage.source_anchor.startswith("span:")
    fact = next(i for i in result.items if i.kind == "fact")
    assert fact.source_anchor.startswith("fact:")
    assert fact.financial_fact_id is not None
    row = next(i for i in result.items if i.kind == "table_row")
    assert row.source_anchor.startswith("table:")
    assert row.table_row_index == 0


def test_hash_mismatch_rejects_passage() -> None:
    result = build_items(mini_corpus(corrupt_passage_hash=True), index_version_id=INDEX)
    codes = {r.code for r in result.rejections}
    assert "HASH_MISMATCH" in codes
    # Corrupted revenue span knocks out that passage + its fact; cost passage remains.
    assert not any(
        i.kind == "passage" and i.source_span_id == "44444444-4444-4444-8444-444444444444"
        for i in result.items
    )
    assert all(i.kind != "fact" for i in result.items)
    assert any(
        i.kind == "passage" and i.source_span_id == "66666666-6666-4666-8666-666666666666"
        for i in result.items
    )
    assert any(i.kind == "table_row" for i in result.items)


def test_idempotent_rebuild() -> None:
    corpus = mini_corpus()
    first = build_items(corpus, index_version_id=INDEX)
    second = build_items(corpus, index_version_id=INDEX)
    assert [i.id for i in first.items] == [i.id for i in second.items]
    assert first.counts == second.counts
    assert first.config_hash == second.config_hash
    assert [r.code for r in first.rejections] == [r.code for r in second.rejections]


def test_dangling_fact_span_rejected_with_diagnostic() -> None:
    corpus = mini_corpus()
    corpus["financial_facts"].append(
        {
            "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "source_span_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "period": "FY2025",
        }
    )
    result = build_items(corpus, index_version_id=INDEX)
    dangling = [r for r in result.rejections if r.code == "UNANCHORED_FACT"]
    assert len(dangling) == 1
    assert dangling[0].financial_fact_id == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert dangling[0].source_span_id == "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    # The dangling fact never becomes an item; the anchored fact still does.
    fact_items = [i for i in result.items if i.kind == "fact"]
    assert len(fact_items) == 1
    assert fact_items[0].financial_fact_id == "77777777-7777-4777-8777-777777777777"
