"""Tests for the storage-adapter selection logic (``get_default_storage``).

Covers the Databricks Unity Catalog volume adapter added in Phase B
(``docs/databricks_integration.md`` §6.6 Step 1): ``DatabricksVolumeStorage`` is a thin
subclass of ``LocalFolderStorage`` selected by env vars. These tests use ``monkeypatch``
to set/clear the relevant env vars — no real Databricks cluster or Unity Catalog volume
is needed. All roots are pointed at ``tmp_path`` folders so construction (which creates
the root dirs) never touches the real DATA_DIR/OUTPUT_DIR.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from classifyos.io.storage import (
    DatabricksVolumeStorage,
    LocalFolderStorage,
    get_default_storage,
)

# The four env vars that steer storage selection/resolution. Cleared before every test so
# a stray value from the ambient environment (or a prior test) can't leak in.
_STORAGE_ENV = (
    "CLASSIFYOS_STORAGE_BACKEND",
    "DBRICKS_INPUT_VOLUME",
    "DBRICKS_OUTPUT_VOLUME",
    "DATA_DIR",
    "OUTPUT_DIR",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all storage-related env vars so each test starts from a known blank slate."""
    for name in _STORAGE_ENV:
        monkeypatch.delenv(name, raising=False)


def _resolved(path: Path) -> Path:
    """Match how LocalFolderStorage normalises a root (``Path(...).resolve()``)."""
    return Path(str(path)).resolve()


def test_default_is_local_folder_storage(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No Databricks env vars → plain LocalFolderStorage, rooted at DATA_DIR/OUTPUT_DIR."""
    data = tmp_path / "input"
    out = tmp_path / "output"
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("OUTPUT_DIR", str(out))

    storage = get_default_storage()

    # Exactly LocalFolderStorage — not the Databricks subclass.
    assert type(storage) is LocalFolderStorage
    assert storage.data_dir == _resolved(data)
    assert storage.output_dir == _resolved(out)


def test_backend_flag_selects_databricks(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CLASSIFYOS_STORAGE_BACKEND=databricks → DatabricksVolumeStorage on the volume roots."""
    vol_in = tmp_path / "vol_in"
    vol_out = tmp_path / "vol_out"
    monkeypatch.setenv("CLASSIFYOS_STORAGE_BACKEND", "databricks")
    monkeypatch.setenv("DBRICKS_INPUT_VOLUME", str(vol_in))
    monkeypatch.setenv("DBRICKS_OUTPUT_VOLUME", str(vol_out))

    storage = get_default_storage()

    assert isinstance(storage, DatabricksVolumeStorage)
    assert storage.data_dir == _resolved(vol_in)
    assert storage.output_dir == _resolved(vol_out)


def test_input_volume_presence_selects_databricks(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """DBRICKS_INPUT_VOLUME set (no backend flag) → DatabricksVolumeStorage.

    With no DBRICKS_OUTPUT_VOLUME, the output root falls back to OUTPUT_DIR — exercising
    the per-root resolution order.
    """
    vol_in = tmp_path / "vol_in"
    out = tmp_path / "output"
    monkeypatch.setenv("DBRICKS_INPUT_VOLUME", str(vol_in))
    monkeypatch.setenv("OUTPUT_DIR", str(out))

    storage = get_default_storage()

    assert isinstance(storage, DatabricksVolumeStorage)
    assert storage.data_dir == _resolved(vol_in)
    # No DBRICKS_OUTPUT_VOLUME → fall back to OUTPUT_DIR.
    assert storage.output_dir == _resolved(out)


def test_explicit_non_databricks_backend_wins_over_input_volume(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An explicit non-'databricks' backend keeps LocalFolderStorage even if a volume is set.

    The DBRICKS_INPUT_VOLUME auto-select only fires when the backend flag is NOT explicitly
    set to something else.
    """
    monkeypatch.setenv("CLASSIFYOS_STORAGE_BACKEND", "local")
    monkeypatch.setenv("DBRICKS_INPUT_VOLUME", str(tmp_path / "vol_in"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "input"))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))

    storage = get_default_storage()

    assert type(storage) is LocalFolderStorage


def test_databricks_backend_falls_back_to_data_dir_when_no_volume(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CLASSIFYOS_STORAGE_BACKEND=databricks but no volume vars → roots fall back to DATA_DIR/OUTPUT_DIR."""
    data = tmp_path / "input"
    out = tmp_path / "output"
    monkeypatch.setenv("CLASSIFYOS_STORAGE_BACKEND", "databricks")
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("OUTPUT_DIR", str(out))

    storage = get_default_storage()

    assert isinstance(storage, DatabricksVolumeStorage)
    assert storage.data_dir == _resolved(data)
    assert storage.output_dir == _resolved(out)


def test_constructor_args_take_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Explicit data_dir/output_dir args beat the DBRICKS_* env vars (notebook use)."""
    monkeypatch.setenv("DBRICKS_INPUT_VOLUME", str(tmp_path / "env_in"))
    monkeypatch.setenv("DBRICKS_OUTPUT_VOLUME", str(tmp_path / "env_out"))
    arg_in = tmp_path / "arg_in"
    arg_out = tmp_path / "arg_out"

    storage = DatabricksVolumeStorage(data_dir=str(arg_in), output_dir=str(arg_out))

    assert storage.data_dir == _resolved(arg_in)
    assert storage.output_dir == _resolved(arg_out)


def test_databricks_storage_round_trips_like_local(tmp_path: Path) -> None:
    """DatabricksVolumeStorage inherits LocalFolderStorage I/O unchanged (save → read → write)."""
    import io

    storage = DatabricksVolumeStorage(
        data_dir=str(tmp_path / "in"), output_dir=str(tmp_path / "out")
    )

    storage.save_input("data.csv", io.BytesIO(b"a,b\n1,2\n"))
    with storage.open_read("data.csv") as fh:
        assert fh.read() == "a,b\n1,2\n"

    with storage.open_write("result.txt") as fh:
        fh.write("done")
    assert Path(storage.path_for("result.txt", output=True)).read_text() == "done"
