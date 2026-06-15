"""Tests for Section 16 (the CLI — inspect-only and full-run modes).

``main()`` is driven in-process (passing ``argv``) so the tests stay fast and can read the
captured stdout. The CLI builds its own ``LocalFolderStorage`` from the environment; the
session fixtures have already pointed ``DATA_DIR`` at the real samples and ``OUTPUT_DIR``
at a temp dir, and ``load_dotenv(override=False)`` inside ``main`` leaves those intact.
"""

from __future__ import annotations

from classifyos.cli import main
from classifyos.runner import METRICS_CSV_KEY, RESULTS_CSV_KEY, RUN_PROFILE_KEY


def test_cli_inspect(storage, output_dir, capsys) -> None:
    """--inspect prints the column/class profile and runs no models."""
    code = main(
        ["--file", "policy_lapse.csv", "--target", "will_lapse", "--inspect"]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "class distribution[will_lapse]" in out
    assert "suggested problem type" in out
    # inspect-only: it must NOT run models / print the metrics table.
    assert "metrics summary" not in out


def test_cli_run(storage, output_dir, capsys) -> None:
    """A small run produces outputs and a metrics summary without error."""
    code = main(
        [
            "--file",
            "policy_lapse.csv",
            "--target",
            "will_lapse",
            "--algos",
            "LR,NB",
            "--balance",
            "class_weight",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "metrics summary" in out
    assert "LogisticRegression" in out and "NaiveBayes" in out
    assert "files written to OUTPUT_DIR" in out

    # the headline artifacts exist
    for key in (RESULTS_CSV_KEY, METRICS_CSV_KEY, RUN_PROFILE_KEY):
        assert storage.exists(key)


def test_cli_missing_file_is_readable(storage, output_dir, capsys) -> None:
    """A missing input file fails readably with a non-zero exit code (no traceback)."""
    code = main(["--file", "does_not_exist.csv", "--target", "will_lapse", "--inspect"])
    assert code == 2
    err = capsys.readouterr().err
    assert "ERROR" in err
