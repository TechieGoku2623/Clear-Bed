"""Train stuck-risk, barrier-type, and avoidable-day models.

The split is time-based: earliest 70% of admissions train, the next 15%
validate, and the last 15% test. Gender and race are not model inputs. They
are used only in the fairness report.

Labels are synthetic. Strong metrics are not clinical validation. See the
model card written next to the saved models.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    roc_auc_score,
)

from clearbed.config import Settings, get_settings
from clearbed.logging import get_logger, log_event
from clearbed.ml.feature_labels import (
    CATEGORICAL_FEATURES,
    FAIRNESS_COLUMNS,
    NUMERIC_FEATURES,
    readable_feature,
)
from clearbed.warehouse import connect

logger = get_logger("ml.train")


@dataclass
class Split:
    """Time-ordered train, validation, and test frames."""

    train: pd.DataFrame
    validate: pd.DataFrame
    test: pd.DataFrame


def time_split(frame: pd.DataFrame) -> Split:
    """Split on admission time. No random shuffle."""
    ordered = frame.sort_values("admit_ts").reset_index(drop=True)
    n = len(ordered)
    if n < 3:
        raise ValueError("Need at least 3 stays to time-split.")
    first = max(int(n * 0.70), 1)
    second = max(int(n * 0.85), first + 1)
    second = min(second, n - 1)
    return Split(
        ordered.iloc[:first].copy(), ordered.iloc[first:second].copy(), ordered.iloc[second:].copy()
    )


def design_matrix(
    frame: pd.DataFrame, columns: list[str] | None = None
) -> tuple[pd.DataFrame, list[str]]:
    """One-hot encode categoricals and align to the training columns."""
    work = frame.copy()
    for column in NUMERIC_FEATURES:
        work[column] = pd.to_numeric(work[column], errors="coerce").fillna(0.0)
    for column in CATEGORICAL_FEATURES:
        work[column] = work[column].fillna("missing").astype(str)
    encoded = pd.get_dummies(
        work[NUMERIC_FEATURES + CATEGORICAL_FEATURES], columns=CATEGORICAL_FEATURES
    )
    if columns is None:
        columns = list(encoded.columns)
    encoded = encoded.reindex(columns=columns, fill_value=0).astype(float)
    return encoded, columns


def _classifier(n_rows: int, *, multiclass: bool) -> lgb.LGBMClassifier:
    small = n_rows < 500
    return lgb.LGBMClassifier(
        n_estimators=40 if small else 160,
        learning_rate=0.08,
        num_leaves=7 if small else 31,
        min_child_samples=1 if small else 20,
        subsample=0.9,
        colsample_bytree=0.9,
        objective="multiclass" if multiclass else "binary",
        random_state=42,
        verbose=-1,
    )


def _regressor(n_rows: int) -> lgb.LGBMRegressor:
    small = n_rows < 500
    return lgb.LGBMRegressor(
        n_estimators=40 if small else 160,
        learning_rate=0.08,
        num_leaves=7 if small else 31,
        min_child_samples=1 if small else 20,
        random_state=42,
        verbose=-1,
    )


def _positive_shap(values: Any) -> np.ndarray:
    """Return a 2-d array of SHAP values for the positive class."""
    if isinstance(values, list):
        return np.asarray(values[1] if len(values) > 1 else values[0])
    array = np.asarray(values)
    if array.ndim == 3:
        return array[:, :, 1] if array.shape[-1] > 1 else array[:, :, 0]
    return array


def _safe_auroc(y_true: np.ndarray, scores: np.ndarray) -> float | None:
    if len(np.unique(y_true)) < 2:
        return None
    return float(roc_auc_score(y_true, scores))


def load_training_frame(settings: Settings | None = None) -> pd.DataFrame:
    """Join admission features to synthetic labels."""
    settings = settings or get_settings()
    con = connect(settings, read_only=True)
    try:
        frame = con.execute(
            """
            select
                f.*,
                l.barrier_type,
                l.avoidable_days,
                cast(l.is_stuck as integer) as is_stuck
            from marts.feat_admission_snapshot as f
            inner join marts.fct_stay_labels as l using (stay_id)
            """
        ).df()
    finally:
        con.close()
    frame["admit_ts"] = pd.to_datetime(frame["admit_ts"])
    return frame


def _fit_stuck(split: Split) -> tuple[dict[str, Any], dict[str, Any], np.ndarray]:
    x_train, columns = design_matrix(split.train)
    x_val, _ = design_matrix(split.validate, columns)
    x_test, _ = design_matrix(split.test, columns)
    y_train = split.train["is_stuck"].astype(int).to_numpy()
    y_val = split.validate["is_stuck"].astype(int).to_numpy()
    y_test = split.test["is_stuck"].astype(int).to_numpy()
    model = _classifier(len(split.train), multiclass=False)
    model.fit(x_train, y_train)
    raw_val = np.asarray(model.predict_proba(x_val), dtype=float)[:, 1]
    calibrator: IsotonicRegression | None = None
    if len(np.unique(y_val)) > 1 and len(y_val) >= 8:
        calibrator = IsotonicRegression(out_of_bounds="clip")
        calibrator.fit(raw_val, y_val)
    raw_test = np.asarray(model.predict_proba(x_test), dtype=float)[:, 1]
    test_scores = calibrator.predict(raw_test) if calibrator is not None else raw_test
    metrics: dict[str, Any] = {
        "auroc": _safe_auroc(y_test, test_scores),
        "auprc": float(average_precision_score(y_test, test_scores))
        if len(np.unique(y_test)) > 1
        else None,
        "brier": float(brier_score_loss(y_test, np.clip(test_scores, 0, 1))),
        "n_test": int(len(y_test)),
        "positive_rate_test": float(np.mean(y_test)),
    }
    bundle = {"model": model, "calibrator": calibrator, "columns": columns, "kind": "stuck_risk"}
    return bundle, metrics, test_scores


def _fit_barrier(split: Split) -> tuple[dict[str, Any], dict[str, Any], np.ndarray, list[str]]:
    train = split.train.loc[split.train["is_stuck"] == 1]
    test = split.test.loc[split.test["is_stuck"] == 1]
    if train.empty or test.empty:
        raise ValueError("Barrier model needs stuck stays in both train and test.")
    x_train, columns = design_matrix(train)
    x_test, _ = design_matrix(test, columns)
    y_train = train["barrier_type"].astype(str)
    y_test = test["barrier_type"].astype(str)
    model = _classifier(len(train), multiclass=True)
    model.fit(x_train, y_train)
    predicted = model.predict(x_test)
    labels = sorted(set(y_train.unique()) | set(y_test.unique()))
    metrics = {
        "macro_f1": float(
            f1_score(y_test, predicted, average="macro", labels=labels, zero_division=0)
        ),
        "n_test_stuck": int(len(y_test)),
        "labels": labels,
    }
    matrix = confusion_matrix(y_test, predicted, labels=labels).tolist()
    bundle = {
        "model": model,
        "calibrator": None,
        "columns": columns,
        "classes": list(model.classes_),
        "kind": "barrier_type",
    }
    return bundle, metrics, matrix, labels


def _fit_days(split: Split) -> tuple[dict[str, Any], dict[str, Any]]:
    x_train, columns = design_matrix(split.train)
    x_test, _ = design_matrix(split.test, columns)
    y_train = split.train["avoidable_days"].astype(float).to_numpy()
    y_test = split.test["avoidable_days"].astype(float).to_numpy()
    model = _regressor(len(split.train))
    model.fit(x_train, y_train)
    predicted = np.clip(model.predict(x_test), 0, None)
    bundle = {"model": model, "calibrator": None, "columns": columns, "kind": "avoidable_days"}
    return bundle, {
        "mae": float(mean_absolute_error(y_test, predicted)),
        "n_test": int(len(y_test)),
    }


def _plot_calibration(y_true: np.ndarray, scores: np.ndarray, path: Path) -> None:
    from sklearn.calibration import calibration_curve

    fig, ax = plt.subplots(figsize=(5, 4))
    if len(np.unique(y_true)) > 1 and len(y_true) >= 10:
        fraction, mean_pred = calibration_curve(
            y_true, np.clip(scores, 0, 1), n_bins=8, strategy="quantile"
        )
        ax.plot(mean_pred, fraction, marker="o", color="#1f6f78")
    ax.plot([0, 1], [0, 1], linestyle="--", color="#8aa0a6")
    ax.set_xlabel("Predicted stuck probability")
    ax.set_ylabel("Observed stuck rate")
    ax.set_title("Calibration")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _plot_confusion(matrix: np.ndarray, labels: list[str], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(6, 5))
    image = ax.imshow(matrix, cmap="Blues")
    ax.set_xticks(range(len(labels)), labels, rotation=30, ha="right")
    ax.set_yticks(range(len(labels)), labels)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Actual")
    ax.set_title("Barrier confusion (stuck stays)")
    fig.colorbar(image, ax=ax, fraction=0.046)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _plot_shap(
    model: lgb.LGBMClassifier, columns: list[str], frame: pd.DataFrame, path: Path
) -> None:
    sample = frame.sample(n=min(400, len(frame)), random_state=42)
    matrix, _ = design_matrix(sample, columns)
    explainer = shap.TreeExplainer(model)
    values = _positive_shap(explainer.shap_values(matrix))
    shap.summary_plot(values, matrix, show=False, max_display=15, plot_size=(8, 5))
    plt.tight_layout()
    plt.savefig(path, dpi=120, bbox_inches="tight")
    plt.close()


def _reasons_from_row(
    columns: list[str], matrix: pd.DataFrame, values: np.ndarray, row: int, top_k: int
) -> list[dict[str, Any]]:
    order = np.argsort(np.abs(values[row]))[::-1][:top_k]
    reasons: list[dict[str, Any]] = []
    for index in order:
        column = columns[int(index)]
        shap_value = float(values[row, int(index)])
        reasons.append(
            {
                "feature": column,
                "label": readable_feature(column),
                "value": float(matrix.iloc[row, int(index)]),
                "shap": round(shap_value, 4),
                "direction": "increases risk" if shap_value >= 0 else "decreases risk",
            }
        )
    return reasons


def explain_frame(
    frame: pd.DataFrame, model_dir: Path, *, top_k: int = 5
) -> list[list[dict[str, Any]]]:
    """Explain every row in ``frame`` with one SHAP pass."""
    bundle = joblib.load(model_dir / "stuck_risk.joblib")
    matrix, _ = design_matrix(frame, bundle["columns"])
    explainer = shap.TreeExplainer(bundle["model"])
    values = _positive_shap(explainer.shap_values(matrix))
    return [
        _reasons_from_row(bundle["columns"], matrix, values, row, top_k)
        for row in range(len(matrix))
    ]


def explain(
    stay_features: dict[str, Any] | pd.DataFrame, model_dir: Path, *, top_k: int = 5
) -> list[dict[str, Any]]:
    """Return the top reasons a stay looks stuck, in plain English."""
    frame = (
        stay_features if isinstance(stay_features, pd.DataFrame) else pd.DataFrame([stay_features])
    )
    return explain_frame(frame, model_dir, top_k=top_k)[0]


def predict_stuck(frame: pd.DataFrame, model_dir: Path) -> np.ndarray:
    """Return calibrated stuck probabilities for ``frame``."""
    bundle = joblib.load(model_dir / "stuck_risk.joblib")
    matrix, _ = design_matrix(frame, bundle["columns"])
    raw = bundle["model"].predict_proba(matrix)[:, 1]
    calibrator = bundle.get("calibrator")
    if calibrator is not None:
        return np.clip(np.asarray(calibrator.predict(raw), dtype=float), 0, 1)
    return np.clip(raw, 0, 1)


def predict_barrier(frame: pd.DataFrame, model_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    """Return the predicted barrier and its class probability."""
    bundle = joblib.load(model_dir / "barrier_type.joblib")
    matrix, _ = design_matrix(frame, bundle["columns"])
    probabilities = bundle["model"].predict_proba(matrix)
    index = probabilities.argmax(axis=1)
    labels = np.asarray(bundle["classes"])[index]
    confidence = probabilities.max(axis=1)
    return labels, confidence


def predict_days(frame: pd.DataFrame, model_dir: Path) -> np.ndarray:
    """Return predicted avoidable days, floored at zero."""
    bundle = joblib.load(model_dir / "avoidable_days.joblib")
    matrix, _ = design_matrix(frame, bundle["columns"])
    return np.clip(bundle["model"].predict(matrix), 0, None)


def _fairness(frame: pd.DataFrame, scores: np.ndarray, path: Path) -> None:
    lines = [
        "# Fairness snapshot",
        "",
        "Gender and race were **not** used as model inputs. Payer type was.",
        "Groups with fewer than 20 test stays, or with only one outcome, are marked insufficient.",
        "These figures describe a synthetic labeling function. They are not a clinical fairness claim.",
        "",
    ]
    y = frame["is_stuck"].astype(int).to_numpy()
    for column in FAIRNESS_COLUMNS:
        lines.append(f"## {column}")
        lines.append("")
        lines.append("| Group | n | positive rate | AUROC |")
        lines.append("| --- | --- | --- | --- |")
        series = frame[column].astype(str).fillna("missing")
        for group, idx in series.groupby(series).groups.items():
            positions = list(idx)
            yy = y[positions]
            ss = scores[positions]
            n = len(positions)
            rate = float(np.mean(yy)) if n else 0.0
            auroc = _safe_auroc(yy, ss) if n >= 20 else None
            auroc_text = f"{auroc:.3f}" if auroc is not None else "insufficient"
            lines.append(f"| {group} | {n} | {rate:.1%} | {auroc_text} |")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _model_card(metrics: dict[str, Any], path: Path) -> None:
    stuck = metrics["stuck_risk"]
    barrier = metrics["barrier_type"]
    days = metrics["avoidable_days"]
    text = f"""# ClearBed model card

Trained: {datetime.now(UTC).isoformat()}

## Data

Synthetic Synthea inpatient stays, joined to a seeded labeling function (`dbt/seeds/labeling_rules.csv`). The checked-in demo population is Massachusetts. CMS facility data is not an input to these models. The placement catalog is the national CMS Care Compare nursing-home file.

Gender and race are excluded from the model matrix and reported only in `reports/fairness.md`.

The split is the earliest 70% of admissions for training, the next 15% for validation (isotonic calibration), and the last 15% for test.

## Metrics (held-out test)

| Model | Metric | Value |
| --- | --- | --- |
| A stuck risk | AUROC | {stuck.get("auroc")} |
| A stuck risk | AUPRC | {stuck.get("auprc")} |
| A stuck risk | Brier | {stuck.get("brier")} |
| B barrier type | macro-F1 | {barrier.get("macro_f1")} |
| C avoidable days | MAE | {days.get("mae")} |

## Limitations

These labels are a noisy function of the same admission features. High discrimination is expected and is **not** evidence the model would rank real discharge delays. Synthea has no discharge disposition.

Do not use the score as a clinical or coverage determination. A case manager approves every referral. The avoidable-day model predicts the synthetic label, not a measured delay.

Replace the labeling function with MIMIC-IV `admissions.discharge_location` before any hospital pilot that claims predictive accuracy.

## Intended use

Rank a morning census so case management looks first at stays the rules and the model both consider likely to wait on placement, payer, guardianship, or home services.
"""
    path.write_text(text, encoding="utf-8")


def _log_mlflow(metrics: dict[str, Any], settings: Settings) -> None:
    import mlflow

    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment("clearbed")
    with mlflow.start_run(run_name="admission_models"):
        stuck = metrics["stuck_risk"]
        for key in ("auroc", "auprc", "brier"):
            if stuck.get(key) is not None:
                mlflow.log_metric(f"stuck_{key}", float(stuck[key]))
        mlflow.log_metric("barrier_macro_f1", float(metrics["barrier_type"]["macro_f1"]))
        mlflow.log_metric("avoidable_days_mae", float(metrics["avoidable_days"]["mae"]))
        mlflow.set_tag("data", "synthetic_synthea")


def train(settings: Settings | None = None, frame: pd.DataFrame | None = None) -> dict[str, Any]:
    """Fit the three models and write artifacts under the configured directories."""
    settings = settings or get_settings()
    data = frame if frame is not None else load_training_frame(settings)
    split = time_split(data)
    stuck_bundle, stuck_metrics, test_scores = _fit_stuck(split)
    barrier_bundle, barrier_metrics, matrix, labels = _fit_barrier(split)
    days_bundle, days_metrics = _fit_days(split)
    metrics: dict[str, Any] = {
        "stuck_risk": stuck_metrics,
        "barrier_type": barrier_metrics,
        "avoidable_days": days_metrics,
        "confusion_matrix": matrix,
        "confusion_labels": labels,
    }
    model_dir = settings.resolved_model_dir
    report_dir = settings.resolved_reports_dir
    model_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(stuck_bundle, model_dir / "stuck_risk.joblib")
    joblib.dump(barrier_bundle, model_dir / "barrier_type.joblib")
    joblib.dump(days_bundle, model_dir / "avoidable_days.joblib")
    _plot_calibration(
        split.test["is_stuck"].astype(int).to_numpy(),
        test_scores,
        report_dir / "calibration_stuck.png",
    )
    _plot_confusion(np.asarray(matrix), labels, report_dir / "confusion_barrier.png")
    _plot_shap(
        stuck_bundle["model"], stuck_bundle["columns"], split.test, report_dir / "shap_stuck.png"
    )
    _fairness(split.test.reset_index(drop=True), test_scores, report_dir / "fairness.md")
    _model_card(metrics, model_dir / "model_card.md")
    (report_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, default=str), encoding="utf-8"
    )
    try:
        _log_mlflow(metrics, settings)
    except Exception as exc:  # noqa: BLE001
        log_event(logger, "mlflow logging failed", error=type(exc).__name__)
    log_event(
        logger,
        "trained models",
        auroc=stuck_metrics.get("auroc"),
        macro_f1=barrier_metrics.get("macro_f1"),
        mae=days_metrics.get("mae"),
    )
    return metrics


def main() -> None:
    """Train from the warehouse and print the test metrics."""
    metrics = train()
    print(json.dumps(metrics, indent=2, default=str))


if __name__ == "__main__":
    main()
