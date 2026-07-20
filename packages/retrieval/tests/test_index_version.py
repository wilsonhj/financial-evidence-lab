from __future__ import annotations

from fel_retrieval import index_version_id, make_index_version_spec

CORPUS = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def test_index_version_id_is_deterministic() -> None:
    kwargs = dict(
        corpus_version_id=CORPUS,
        config_hash="sha256:" + ("0" * 64),
        provider="mock",
        model="mock-embed-v1",
    )
    assert index_version_id(**kwargs) == index_version_id(**kwargs)


def test_index_version_id_changes_with_each_pin() -> None:
    base = dict(
        corpus_version_id=CORPUS,
        config_hash="sha256:" + ("0" * 64),
        provider="mock",
        model="mock-embed-v1",
    )
    baseline = index_version_id(**base)
    assert (
        index_version_id(**{**base, "corpus_version_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"})
        != baseline
    )
    assert index_version_id(**{**base, "config_hash": "sha256:" + ("1" * 64)}) != baseline
    assert index_version_id(**{**base, "provider": "openai"}) != baseline
    assert index_version_id(**{**base, "model": "text-embedding-3-small"}) != baseline


def test_spec_reuses_id_for_identical_config() -> None:
    a = make_index_version_spec(
        corpus_version_id=CORPUS, embedding_provider="mock", embedding_model="mock-embed-v1"
    )
    b = make_index_version_spec(
        corpus_version_id=CORPUS, embedding_provider="mock", embedding_model="mock-embed-v1"
    )
    assert a.id == b.id
    assert a.config_hash == b.config_hash
    assert a.dimensions == 512
    assert a.distance == "cosine"


def test_spec_mints_new_id_on_config_change() -> None:
    a = make_index_version_spec(
        corpus_version_id=CORPUS, embedding_provider="mock", embedding_model="mock-embed-v1"
    )
    b = make_index_version_spec(
        corpus_version_id=CORPUS,
        embedding_provider="mock",
        embedding_model="mock-embed-v1",
        chunker_config={"kinds": ["passage"]},
    )
    assert a.config_hash != b.config_hash
    assert a.id != b.id
