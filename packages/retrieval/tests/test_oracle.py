from __future__ import annotations

import pytest

from fel_retrieval import cosine_distance, exact_knn, recall_at_k


def test_cosine_distance_identical_is_zero() -> None:
    assert cosine_distance([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(0.0, abs=1e-12)


def test_cosine_distance_orthogonal_is_one() -> None:
    assert cosine_distance([1.0, 0.0], [0.0, 1.0]) == pytest.approx(1.0)


def test_exact_knn_orders_by_distance_and_breaks_ties_on_id() -> None:
    items = [
        ("far", [0.0, 1.0]),
        ("near", [1.0, 0.01]),
        ("tie_b", [1.0, 0.0]),
        ("tie_a", [1.0, 0.0]),
    ]
    top = exact_knn([1.0, 0.0], items, k=3)
    assert top[0] in {"tie_a", "tie_b"}
    assert top[1] in {"tie_a", "tie_b"}
    assert top[:2] == ["tie_a", "tie_b"]  # deterministic id tie-break
    assert top[2] == "near"


def test_recall_at_k() -> None:
    exact = ["a", "b", "c", "d"]
    assert recall_at_k(exact, ["a", "b", "c", "d"], 4) == 1.0
    assert recall_at_k(exact, ["a", "b", "x", "y"], 4) == 0.5
    assert recall_at_k(exact, ["z"], 4) == 0.0


def test_recall_at_k_requires_positive_k() -> None:
    with pytest.raises(ValueError):
        recall_at_k(["a"], ["a"], 0)
