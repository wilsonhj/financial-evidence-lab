from fel_retrieval import CHUNKER_VERSION, config_hash, item_id, source_anchor


def test_source_anchor_kinds() -> None:
    assert source_anchor("passage", source_span_id="s1") == "span:s1"
    assert source_anchor("fact", source_span_id="s1", financial_fact_id="f1") == "fact:f1"
    assert (
        source_anchor("table_row", source_span_id="s1", table_id="t1", table_row_index=2)
        == "table:t1:2"
    )


def test_item_id_stable() -> None:
    a = item_id("idx", "passage", "span:s1", "sha256:" + ("a" * 64))
    b = item_id("idx", "passage", "span:s1", "sha256:" + ("a" * 64))
    assert a == b
    c = item_id("idx", "passage", "span:s1", "sha256:" + ("b" * 64))
    assert a != c


def test_config_hash_changes_with_config() -> None:
    base = config_hash({"chunker_version": CHUNKER_VERSION, "kinds": ["passage"]})
    other = config_hash({"chunker_version": CHUNKER_VERSION, "kinds": ["passage", "fact"]})
    assert base.startswith("sha256:")
    assert base != other
