"""The canonical set of output artifacts a run produces.

ClassifyOS always writes the same 11 files to ``OUTPUT_DIR`` (the engine guarantees the set
is complete — degenerate plots fall back to labelled placeholders rather than being skipped).
Listing them by logical key here, in one place, lets ``/run`` report them and ``/outputs``
enumerate/stream them without re-deriving the list. PNGs are referenced by name only and
fetched on demand via ``/outputs/{name}`` — never base64-inlined into a JSON response.
"""

from __future__ import annotations

from pathlib import Path

from classifyos.io.storage import StorageAdapter

# The artifacts, in a stable display order: CSVs + the run profile, then the six plots.
ARTIFACT_KEYS: tuple[str, ...] = (
    "classification_results.csv",   # full per-sample predictions (Section 15)
    "metrics_comparison.csv",       # one summary row per model (Section 15)
    "class_report.csv",             # per-class per-model report (Section 15)
    "feature_impact_summary.csv",   # ranked raw feature impact, pre-training (Section 5)
    "feature_importance_summary.csv",  # native per-model importance, post-training (Section 15)
    "permutation_importance_summary.csv",  # model-agnostic permutation importance, post-training
    "explanations_summary.csv",     # per-row SHAP contributions (only when explainability is enabled)
    "run_profile.json",             # audit record of the run (Section 15)
    "plot1_confusion_matrix.png",   # Section 14
    "plot2_roc_pr_curves.png",      # Section 14
    "plot3_feature_importance.png", # Section 14
    "plot4_feature_impact.png",     # Section 5
    "plot5_calibration_curve.png",  # Section 14
    "plot6_interaction_summary.png",# Section 7B
)


def collect_artifacts(storage: StorageAdapter) -> list[dict[str, object]]:
    """List the known artifacts currently present in the OUTPUT root.

    Resolves each artifact key to a concrete path via the storage adapter (the
    adapter-sanctioned way to obtain a real filesystem path) and returns one
    ``{name, suffix, size_bytes}`` entry per file that actually exists. Shared by both
    ``/api/v1/run`` (the ``artifacts`` block) and ``/api/v1/outputs`` so the two agree.
    """
    entries: list[dict[str, object]] = []
    for key in ARTIFACT_KEYS:
        path = Path(storage.path_for(key, output=True))
        if path.exists():
            entries.append(
                {"name": key, "suffix": path.suffix, "size_bytes": path.stat().st_size}
            )
    return entries
