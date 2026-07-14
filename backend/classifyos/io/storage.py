"""Storage abstraction for ClassifyOS.

ALL file I/O in the ML engine and API MUST go through a ``StorageAdapter``.
Pipeline code must never call :func:`open` directly or hardcode filesystem paths.

:class:`LocalFolderStorage` reads/writes under the ``DATA_DIR`` (inputs) and
``OUTPUT_DIR`` (artifacts) folders configured via environment variables.
:class:`DatabricksVolumeStorage` is a thin subclass of it whose roots point at Unity
Catalog volume paths (Databricks Runtime 13.3 LTS+, POSIX-style ``/Volumes/...``) — a
drop-in behind the same interface, selected at startup by :func:`get_default_storage`
without touching any pipeline code.

Resolution rules (LocalFolderStorage):
    * A logical key is interpreted relative to a *root* — ``DATA_DIR`` for reads of
      input data, ``OUTPUT_DIR`` for writes of artifacts. Callers pick the root by
      using the read/write helpers; ``open_read`` defaults to the data root and
      ``open_write`` defaults to the output root.
    * Resolved paths are confined to their root (no path traversal escapes).
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import IO, Iterable


class StorageAdapter(ABC):
    """Abstract base class for all storage backends.

    Concrete adapters map *logical keys* (e.g. ``"samples/lapse.csv"``) onto a
    physical backend (local folders now, Databricks volumes later). Keys use POSIX
    ``/`` separators regardless of host OS.
    """

    @abstractmethod
    def open_read(self, key: str, *, binary: bool = False) -> IO:
        """Open a stored object for reading and return a file-like object.

        Args:
            key: Logical key, relative to the adapter's input root.
            binary: Open in binary mode when ``True``; text mode otherwise.
        """

    @abstractmethod
    def open_write(self, key: str, *, binary: bool = False) -> IO:
        """Open a destination for writing and return a file-like object.

        Parent "directories" are created as needed. ``key`` is relative to the
        adapter's output root.
        """

    @abstractmethod
    def save_input(self, key: str, fileobj: IO) -> str:
        """Persist an uploaded byte stream into the *input* root and return its key.

        This is the write-side twin of :meth:`open_read`: ``open_write`` targets the
        OUTPUT root (artifacts), but an uploaded dataset must land in the INPUT root so
        that :func:`~classifyos.io.inspect.inspect_file` and
        :func:`~classifyos.io.loader.data_loader` (which read via :meth:`open_read`) can
        find it afterwards. Added in Phase 8 to keep file uploads behind the storage
        abstraction (CLAUDE.md: ALL file I/O goes through ``StorageAdapter``) — see the
        plan_tweak deviation row.

        Args:
            key: Logical key, relative to the adapter's input root. Parent
                "directories" are created as needed; path-traversal escapes are rejected.
            fileobj: A binary file-like object (e.g. ``fastapi.UploadFile.file``) whose
                contents are copied verbatim.

        Returns:
            The logical key the data was stored under (echoes ``key``), suitable for
            passing back to ``inspect_file`` / a run config's ``input_file``.
        """

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return whether an object exists for ``key`` (checks both roots)."""

    @abstractmethod
    def list(self, prefix: str = "") -> Iterable[str]:
        """Yield logical keys under ``prefix`` (searches the input root)."""

    @abstractmethod
    def path_for(self, key: str, *, output: bool = False) -> str:
        """Return a concrete path/URI for ``key``.

        Provided for libraries that require a real filesystem path (e.g. pandas,
        matplotlib ``savefig``). Use sparingly — prefer the file-like helpers.

        Args:
            key: Logical key.
            output: Resolve against the output root when ``True``; input root otherwise.
        """


class LocalFolderStorage(StorageAdapter):
    """Local-filesystem adapter backed by ``DATA_DIR`` and ``OUTPUT_DIR``.

    Reads resolve under ``data_dir`` (inputs) and writes resolve under
    ``output_dir`` (artifacts). Both roots are created if missing.

    Args:
        data_dir: Input root. Defaults to the ``DATA_DIR`` env var, then ``./data``.
        output_dir: Output root. Defaults to the ``OUTPUT_DIR`` env var, then
            ``./classification_output``.
    """

    def __init__(self, data_dir: str | None = None, output_dir: str | None = None) -> None:
        self.data_dir = Path(data_dir or os.environ.get("DATA_DIR", "data")).resolve()
        self.output_dir = Path(
            output_dir or os.environ.get("OUTPUT_DIR", "classification_output")
        ).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # -- internal helpers -------------------------------------------------

    def _resolve(self, key: str, root: Path) -> Path:
        """Resolve ``key`` under ``root``, rejecting path-traversal escapes."""
        candidate = (root / key.lstrip("/")).resolve()
        if root not in candidate.parents and candidate != root:
            raise ValueError(f"Resolved path for {key!r} escapes root {root}")
        return candidate

    # -- StorageAdapter API ----------------------------------------------

    def open_read(self, key: str, *, binary: bool = False) -> IO:
        path = self._resolve(key, self.data_dir)
        return open(path, "rb" if binary else "r", encoding=None if binary else "utf-8")

    def open_write(self, key: str, *, binary: bool = False) -> IO:
        path = self._resolve(key, self.output_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        return open(path, "wb" if binary else "w", encoding=None if binary else "utf-8")

    def save_input(self, key: str, fileobj: IO) -> str:
        # Resolve under the INPUT root (data_dir), not the output root — uploaded data
        # must be readable by inspect_file/data_loader, which read from data_dir.
        import shutil

        path = self._resolve(key, self.data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as dst:
            shutil.copyfileobj(fileobj, dst)
        return key

    def exists(self, key: str) -> bool:
        return (
            self._resolve(key, self.data_dir).exists()
            or self._resolve(key, self.output_dir).exists()
        )

    def list(self, prefix: str = "") -> Iterable[str]:
        base = self._resolve(prefix, self.data_dir) if prefix else self.data_dir
        if not base.exists():
            return
        for path in sorted(base.rglob("*")):
            if path.is_file():
                yield path.relative_to(self.data_dir).as_posix()

    def path_for(self, key: str, *, output: bool = False) -> str:
        root = self.output_dir if output else self.data_dir
        path = self._resolve(key, root)
        if output:
            path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)


class DatabricksVolumeStorage(LocalFolderStorage):
    """Unity Catalog volume adapter (Databricks Runtime 13.3 LTS+).

    Unity Catalog volumes expose POSIX paths (``/Volumes/<catalog>/<schema>/<vol>/...``)
    that are directly usable with Python :func:`open`, ``pathlib``, pandas, and
    matplotlib — from the engine's perspective a volume path is indistinguishable from a
    local folder. This adapter is therefore a *thin* subclass of
    :class:`LocalFolderStorage` whose two roots default to volume paths taken from the
    environment. No pipeline code changes: every ``open_read``/``open_write``/``path_for``
    call resolves through the inherited local-folder logic.

    Root resolution (first that is set wins), per root:
        1. ``data_dir`` / ``output_dir`` passed directly to ``__init__`` (useful in a
           notebook where the catalog/schema/volume are known at runtime).
        2. ``DBRICKS_INPUT_VOLUME`` / ``DBRICKS_OUTPUT_VOLUME`` env vars — the volume
           paths, e.g. ``/Volumes/main/classifyos/data/input``.
        3. ``DATA_DIR`` / ``OUTPUT_DIR`` (the existing local defaults), then the same
           ultimate ``data`` / ``classification_output`` relative fallbacks.

    All ``StorageAdapter`` guarantees (path-traversal protection, parent-directory
    creation, the input-vs-output root split) are inherited unchanged.
    """

    def __init__(self, data_dir: str | None = None, output_dir: str | None = None) -> None:
        resolved_data = (
            data_dir
            or os.environ.get("DBRICKS_INPUT_VOLUME")
            or os.environ.get("DATA_DIR", "data")
        )
        resolved_output = (
            output_dir
            or os.environ.get("DBRICKS_OUTPUT_VOLUME")
            or os.environ.get("OUTPUT_DIR", "classification_output")
        )
        super().__init__(data_dir=resolved_data, output_dir=resolved_output)


def get_default_storage() -> StorageAdapter:
    """Return the configured storage adapter.

    Selection order:
        1. ``CLASSIFYOS_STORAGE_BACKEND=databricks``  → :class:`DatabricksVolumeStorage`
        2. ``DBRICKS_INPUT_VOLUME`` present (and the backend not set to something else)
           → :class:`DatabricksVolumeStorage`
        3. default                                    → :class:`LocalFolderStorage`

    Local runs with neither env var set continue to get :class:`LocalFolderStorage` —
    no behaviour change whatsoever.
    """
    backend = os.environ.get("CLASSIFYOS_STORAGE_BACKEND", "").lower()
    if backend == "databricks" or (not backend and os.environ.get("DBRICKS_INPUT_VOLUME")):
        return DatabricksVolumeStorage()
    return LocalFolderStorage()
