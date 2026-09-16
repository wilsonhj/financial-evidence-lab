"""Only named disposable local harness targets receive a mode marker."""

from pathlib import Path

import pytest

from benchmarks.synthetic_target import prepare_synthetic_target


@pytest.fixture(autouse=True)
def explicit_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEL_DEPLOYMENT_MODE", "synthetic-http")
    monkeypatch.setenv("FEL_AUTH_MODE", "mock")
    monkeypatch.setenv("FEL_ALLOW_MOCK_LLM", "1")
    monkeypatch.delenv("PGHOSTADDR", raising=False)
    monkeypatch.delenv("PGSERVICE", raising=False)


def test_named_target_is_idempotent(tmp_path: Path) -> None:
    storage = tmp_path / "store"
    for _ in range(2):
        prepare_synthetic_target(
            "postgresql://localhost/fel_load_test", storage, "local-load", "fel_load"
        )
    assert (storage / ".synthetic-http-target").read_bytes() == b"local-load"


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://remote/fel_load_test",
        "postgresql:///fel_load_test",
        "host=localhost hostaddr=10.0.0.1 dbname=fel_load_test",
        "host=localhost service=remote dbname=fel_load_test",
        "host=localhost,remote dbname=fel_load_test",
        "postgresql://localhost/customer",
    ],
)
def test_unapproved_database_never_creates_marker(tmp_path: Path, dsn: str) -> None:
    with pytest.raises(ValueError, match="Synthetic target configuration unavailable"):
        prepare_synthetic_target(dsn, tmp_path, "local-load", "fel_load")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "name,value",
    [
        ("FEL_DEPLOYMENT_MODE", "public"),
        ("FEL_AUTH_MODE", "supabase"),
        ("FEL_ALLOW_MOCK_LLM", "0"),
        ("PGHOSTADDR", "10.0.0.1"),
        ("PGSERVICE", "remote"),
    ],
)
def test_explicit_modes_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        prepare_synthetic_target(
            "postgresql://localhost/fel_load_test", tmp_path, "local-load", "fel_load"
        )
    assert not list(tmp_path.iterdir())


def test_foreign_or_unmarked_storage_is_not_claimed(tmp_path: Path) -> None:
    marker = tmp_path / ".synthetic-http-target"
    marker.write_text("other-target")
    with pytest.raises(ValueError):
        prepare_synthetic_target(
            "postgresql://localhost/fel_load_test", tmp_path, "local-load", "fel_load"
        )
    assert marker.read_text() == "other-target"
    marker.unlink()
    (tmp_path / "existing-data").write_text("preserve")
    with pytest.raises(ValueError):
        prepare_synthetic_target(
            "postgresql://localhost/fel_load_test", tmp_path, "local-load", "fel_load"
        )
    assert not marker.exists()


@pytest.mark.parametrize("target", ["", "ab", "with space", "x" * 81, "target\n"])
def test_target_syntax(tmp_path: Path, target: str) -> None:
    with pytest.raises(ValueError):
        prepare_synthetic_target(
            "postgresql://localhost/fel_load_test", tmp_path, target, "fel_load"
        )
