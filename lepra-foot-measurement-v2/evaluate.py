"""
evaluate.py
===========
Evaluation framework for the foot measurement pipeline.

Compares pipeline (image-based) measurements against manual ground truth.
Handles the real-world data quality issues in the Firebase export:
  - v1 app default/placeholder values in image measurements
  - Field confusion in manual measurements (width vs girth, arch height misuse)
  - Mixed units (cm in DB, mm in pipeline output)

Usage
-----
    # Analyse the Firebase export (data quality report + v1-vs-manual comparison)
    python evaluate.py --db path/to/firebase_export.json

    # Evaluate v2 pipeline predictions against the same DB
    python evaluate.py --db path/to/firebase_export.json --preds outputs/eval_predictions/

    # Write results to file instead of stdout
    python evaluate.py --db path/to/firebase_export.json -o eval_report.txt
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Optional

import numpy as np


# ─── Plausibility bounds (cm) for adult foot measurements ──────────
# Source: ISO 9407 / Brannock device norms / clinical podiatry literature.
# Anything outside these ranges is almost certainly a data entry error.
PLAUSIBLE_CM = {
    "length":     (15.0, 35.0),   # foot length
    "width":      (6.0, 14.0),    # forefoot width (NOT girth)
    "archHeight": (1.5, 8.0),     # medial arch height
    "ballGirth":  (17.0, 32.0),   # ball-of-foot circumference
    "instep":     (18.0, 34.0),   # instep circumference
}

# Known default / placeholder values from the v1 image-measurement app.
# Records where ALL of these match are excluded as non-real measurements.
V1_DEFAULT_TEMPLATES = [
    # Template A: seen in ~115 records
    {"widthLeft": 9.8, "ballGirthLeft": 23.5, "instepLeft": 24.1},
    # Template B: seen in ~158 records
    {"ballGirthLeft": 35.0, "instepLeft": 35.0},
]

# Mapping: Firebase field base name → pipeline output key
DB_TO_PIPELINE = {
    "length":     "foot_length_mm",
    "width":      "forefoot_width_mm",
    "archHeight": "arch_height_mm",
    "ballGirth":  "ball_girth_mm",
    "instep":     "instep_girth_mm",
}


# ─── Helpers ────────────────────────────────────────────────────────

def to_float(v) -> Optional[float]:
    """Safely convert a value to float, returning None on failure."""
    if isinstance(v, (int, float)):
        return float(v) if not math.isnan(v) else None
    if isinstance(v, str) and v.strip():
        try:
            f = float(v)
            return f if not math.isnan(f) else None
        except ValueError:
            return None
    return None


def is_v1_default(im: dict) -> bool:
    """Check whether an imageMeasurements dict matches a known v1 default template."""
    for template in V1_DEFAULT_TEMPLATES:
        if all(to_float(im.get(k)) == v for k, v in template.items()):
            return True
    return False


def is_plausible(field_base: str, value_cm: float) -> bool:
    """Check whether a measurement value (in cm) is physiologically plausible."""
    lo, hi = PLAUSIBLE_CM.get(field_base, (0.0, 999.0))
    return lo <= value_cm <= hi


# ─── Metric calculations ───────────────────────────────────────────

def compute_metrics(predicted: np.ndarray, reference: np.ndarray) -> dict:
    """
    Compute agreement metrics between two arrays of paired measurements.
    Both arrays must be the same length, in the same units.

    Returns dict with:
      n, mae, rmse, bias (mean signed error), std_diff,
      p5_err, p95_err, loa_lower, loa_upper (Bland-Altman limits of agreement),
      pearson_r, icc
    """
    n = len(predicted)
    if n < 2:
        return {"n": n, "mae": float("nan"), "note": "insufficient_data"}

    diff = predicted - reference          # signed error
    abs_diff = np.abs(diff)
    bias = float(np.mean(diff))
    std_diff = float(np.std(diff, ddof=1))
    mae = float(np.mean(abs_diff))
    rmse = float(np.sqrt(np.mean(diff ** 2)))
    p5 = float(np.percentile(abs_diff, 5))
    p50 = float(np.percentile(abs_diff, 50))
    p95 = float(np.percentile(abs_diff, 95))

    # Bland-Altman limits of agreement (mean diff ± 1.96 SD)
    loa_lower = bias - 1.96 * std_diff
    loa_upper = bias + 1.96 * std_diff

    # Pearson correlation
    if np.std(predicted) > 0 and np.std(reference) > 0:
        pearson_r = float(np.corrcoef(predicted, reference)[0, 1])
    else:
        pearson_r = float("nan")

    # ICC(3,1) — two-way mixed, single measures, consistency
    icc = _icc_31(predicted, reference)

    return {
        "n": n,
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "bias": round(bias, 2),
        "std_diff": round(std_diff, 2),
        "p5_abs_err": round(p5, 2),
        "p50_abs_err": round(p50, 2),
        "p95_abs_err": round(p95, 2),
        "loa_lower": round(loa_lower, 2),
        "loa_upper": round(loa_upper, 2),
        "pearson_r": round(pearson_r, 4),
        "icc_31": round(icc, 4),
    }


def _icc_31(x: np.ndarray, y: np.ndarray) -> float:
    """
    ICC(3,1) — two-way mixed model, single measures, consistency.
    Treats one rater as fixed (manual) and one as random (pipeline).
    """
    n = len(x)
    if n < 3:
        return float("nan")

    data = np.column_stack([x, y])  # (n, 2)
    k = 2  # number of raters

    grand_mean = data.mean()
    row_means = data.mean(axis=1)
    col_means = data.mean(axis=0)

    ss_total = np.sum((data - grand_mean) ** 2)
    ss_rows = k * np.sum((row_means - grand_mean) ** 2)
    ss_cols = n * np.sum((col_means - grand_mean) ** 2)
    ss_error = ss_total - ss_rows - ss_cols

    ms_rows = ss_rows / (n - 1)
    ms_error = ss_error / ((n - 1) * (k - 1))

    denom = ms_rows + ms_error
    if denom == 0:
        return float("nan")
    return float((ms_rows - ms_error) / denom)


# ─── Data loading ───────────────────────────────────────────────────

def load_firebase_db(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def extract_paired_data(db: dict) -> dict:
    """
    Extract paired (image, manual) measurements from the Firebase export.

    Returns a dict keyed by measurement name, e.g.:
      {
        "lengthLeft": {"image_cm": [...], "manual_cm": [...], "record_ids": [...]},
        ...
      }

    Applies:
      1. v1 default template filtering (image side)
      2. Plausibility filtering (both sides)
    """
    sides = ("Left", "Right")
    bases = ("length", "width", "archHeight", "ballGirth", "instep")
    fields = [f"{base}{side}" for base in bases for side in sides]

    result = {f: {"image_cm": [], "manual_cm": [], "record_ids": []} for f in fields}
    stats = {
        "total": 0,
        "has_both_objects": 0,
        "v1_defaults_skipped": 0,
        "plausibility_rejects": {f: {"image": 0, "manual": 0} for f in fields},
    }

    for rec_id, rec in db.items():
        stats["total"] += 1
        im = rec.get("imageMeasurements")
        mm = rec.get("manualMeasurements")

        if not isinstance(im, dict) or not isinstance(mm, dict):
            continue
        stats["has_both_objects"] += 1

        if is_v1_default(im):
            stats["v1_defaults_skipped"] += 1
            continue

        for field_name in fields:
            base = field_name.replace("Left", "").replace("Right", "")
            iv = to_float(im.get(field_name))
            mv = to_float(mm.get(field_name))

            if iv is None or mv is None or iv <= 0 or mv <= 0:
                continue

            if not is_plausible(base, iv):
                stats["plausibility_rejects"][field_name]["image"] += 1
                continue
            if not is_plausible(base, mv):
                stats["plausibility_rejects"][field_name]["manual"] += 1
                continue

            result[field_name]["image_cm"].append(iv)
            result[field_name]["manual_cm"].append(mv)
            result[field_name]["record_ids"].append(rec_id)

    return result, stats


def load_pipeline_predictions(pred_dir: str, db: dict) -> dict:
    """
    Load v2 pipeline prediction JSONs and match them to the Firebase DB
    using patient_id.

    Returns a dict keyed by measurement name:
      {
        "lengthLeft": {"pipeline_cm": [...], "manual_cm": [...], "patient_ids": [...]},
        ...
      }
    """
    pred_path = Path(pred_dir)
    pred_files = sorted(pred_path.glob("*.json"))
    if not pred_files:
        return None, {"error": f"No JSON files found in {pred_dir}"}

    # Build lookup: patient_id -> manual measurements from DB
    manual_by_patient = {}
    for rec_id, rec in db.items():
        pid = rec.get("patientId", "")
        mm = rec.get("manualMeasurements")
        if not isinstance(mm, dict) or not pid:
            continue
        manual_by_patient[pid] = mm

    side_map = {"left": "Left", "right": "Right"}
    bases_pipeline_to_db = {
        "foot_length_mm": "length",
        "forefoot_width_mm": "width",
        "arch_height_mm": "archHeight",
        "ball_girth_mm": "ballGirth",
        "ball_girth_mm_provisional": "ballGirth",
        "instep_girth_mm": "instep",
        "instep_girth_mm_provisional": "instep",
    }

    fields = [f"{base}{side}" for base in ("length", "width", "archHeight", "ballGirth", "instep")
              for side in ("Left", "Right")]
    result = {f: {"pipeline_cm": [], "manual_cm": [], "patient_ids": []} for f in fields}
    stats = {"n_predictions": len(pred_files), "n_matched": 0, "n_unmatched": 0}

    for pf in pred_files:
        with open(pf, encoding="utf-8") as f:
            pred = json.load(f)

        pid = pred.get("patient_id", pf.stem)
        manual = manual_by_patient.get(pid)
        if manual is None:
            stats["n_unmatched"] += 1
            continue
        stats["n_matched"] += 1

        for side_key, side_suffix in side_map.items():
            side_data = pred.get(side_key, {})
            if not isinstance(side_data, dict):
                continue

            for pipeline_key, db_base in bases_pipeline_to_db.items():
                meas = side_data.get(pipeline_key)
                if not isinstance(meas, dict):
                    continue

                val_mm = to_float(meas.get("value_mm"))
                if val_mm is None or val_mm <= 0:
                    continue
                val_cm = val_mm / 10.0  # convert pipeline mm → cm

                field_name = f"{db_base}{side_suffix}"
                manual_val = to_float(manual.get(field_name))
                if manual_val is None or manual_val <= 0:
                    continue
                if not is_plausible(db_base, manual_val):
                    continue

                result[field_name]["pipeline_cm"].append(val_cm)
                result[field_name]["manual_cm"].append(manual_val)
                result[field_name]["patient_ids"].append(pid)

    return result, stats


# ─── Report generation ──────────────────────────────────────────────

def format_report(
    db_path: str,
    paired_data: dict,
    paired_stats: dict,
    pipeline_data: Optional[dict] = None,
    pipeline_stats: Optional[dict] = None,
) -> str:
    lines = []
    w = 72  # report width

    lines.append("=" * w)
    lines.append("  FOOT MEASUREMENT PIPELINE — EVALUATION REPORT")
    lines.append("=" * w)
    lines.append(f"\n  Data source: {db_path}")
    lines.append(f"  Total records in DB: {paired_stats['total']}")
    lines.append(f"  Records with both image + manual objects: {paired_stats['has_both_objects']}")
    lines.append(f"  v1 default templates filtered out: {paired_stats['v1_defaults_skipped']}")
    lines.append(f"  Candidate records after v1 filter: {paired_stats['has_both_objects'] - paired_stats['v1_defaults_skipped']}")

    # ── Section 1: Data Quality ─────────────────────────────────────
    lines.append(f"\n{'─' * w}")
    lines.append("  SECTION 1: DATA QUALITY ASSESSMENT")
    lines.append(f"{'─' * w}")

    lines.append("\n  Plausibility bounds applied (cm):")
    for name, (lo, hi) in PLAUSIBLE_CM.items():
        lines.append(f"    {name:<14} {lo:>5.1f} – {hi:>5.1f}")

    lines.append("\n  Plausibility rejects per field:")
    lines.append(f"    {'Field':<22} {'Image rejects':>14} {'Manual rejects':>15}")
    lines.append(f"    {'─'*22} {'─'*14} {'─'*15}")
    for field, rej in paired_stats["plausibility_rejects"].items():
        if rej["image"] > 0 or rej["manual"] > 0:
            lines.append(f"    {field:<22} {rej['image']:>14} {rej['manual']:>15}")

    lines.append("\n  Usable paired samples after all filtering:")
    lines.append(f"    {'Field':<22} {'n':>6}")
    lines.append(f"    {'─'*22} {'─'*6}")
    for field in sorted(paired_data.keys()):
        n = len(paired_data[field]["image_cm"])
        if n > 0:
            lines.append(f"    {field:<22} {n:>6}")

    # ── Section 2: v1 Image vs Manual ───────────────────────────────
    lines.append(f"\n{'─' * w}")
    lines.append("  SECTION 2: v1 APP (IMAGE) vs MANUAL — AGREEMENT METRICS")
    lines.append(f"{'─' * w}")
    lines.append("  Note: These are v1 app values, NOT the current v2 pipeline.")
    lines.append("  Units: centimetres (cm)\n")

    # Group by measurement base for cleaner display
    bases = ["length", "width", "archHeight", "ballGirth", "instep"]
    for base in bases:
        for side in ("Left", "Right"):
            field = f"{base}{side}"
            d = paired_data.get(field)
            if not d or len(d["image_cm"]) < 2:
                continue
            img = np.array(d["image_cm"])
            man = np.array(d["manual_cm"])
            m = compute_metrics(img, man)

            lines.append(f"  {field}")
            lines.append(f"    n={m['n']}  MAE={m['mae']:.2f}cm  RMSE={m['rmse']:.2f}cm  "
                          f"Bias={m['bias']:+.2f}cm")
            lines.append(f"    P50={m['p50_abs_err']:.2f}cm  P95={m['p95_abs_err']:.2f}cm  "
                          f"r={m['pearson_r']:.3f}  ICC={m['icc_31']:.3f}")
            lines.append(f"    Bland-Altman LoA: [{m['loa_lower']:.2f}, {m['loa_upper']:+.2f}]cm")
            lines.append("")

    # ── Section 3: v2 Pipeline vs Manual ────────────────────────────
    if pipeline_data is not None:
        lines.append(f"{'─' * w}")
        lines.append("  SECTION 3: v2 PIPELINE vs MANUAL — AGREEMENT METRICS")
        lines.append(f"{'─' * w}")
        lines.append(f"  Predictions dir: {pipeline_stats}")
        lines.append("  Units: centimetres (cm)\n")

        has_any = False
        for base in bases:
            for side in ("Left", "Right"):
                field = f"{base}{side}"
                d = pipeline_data.get(field)
                if not d or len(d["pipeline_cm"]) < 2:
                    continue
                has_any = True
                pred = np.array(d["pipeline_cm"])
                man = np.array(d["manual_cm"])
                m = compute_metrics(pred, man)

                lines.append(f"  {field}")
                lines.append(f"    n={m['n']}  MAE={m['mae']:.2f}cm  RMSE={m['rmse']:.2f}cm  "
                              f"Bias={m['bias']:+.2f}cm")
                lines.append(f"    P50={m['p50_abs_err']:.2f}cm  P95={m['p95_abs_err']:.2f}cm  "
                              f"r={m['pearson_r']:.3f}  ICC={m['icc_31']:.3f}")
                lines.append(f"    Bland-Altman LoA: [{m['loa_lower']:.2f}, {m['loa_upper']:+.2f}]cm")
                lines.append("")

        if not has_any:
            lines.append("  No matched predictions with sufficient data found.")
            lines.append("  Ensure pipeline JSON patient_id matches DB patientId,")
            lines.append("  and that manual measurements exist for those patients.")
            lines.append("")

    # ── Section 4: Clinical Acceptability ────────────────────────────
    lines.append(f"{'─' * w}")
    lines.append("  SECTION 4: CLINICAL ACCEPTABILITY THRESHOLDS")
    lines.append(f"{'─' * w}")
    lines.append("""
  For therapeutic footwear (leprosy/diabetic foot), published tolerances are:
    Foot length:     ± 5 mm  (± 0.5 cm)
    Forefoot width:  ± 3 mm  (± 0.3 cm)
    Arch height:     ± 3 mm  (± 0.3 cm)
    Ball girth:      ± 5 mm  (± 0.5 cm)
    Instep girth:    ± 5 mm  (± 0.5 cm)

  Target: >90% of measurements within these tolerances.
  Current status: Cannot reliably assess — see data quality issues above.
""")

    # ── Section 5: Recommendations ──────────────────────────────────
    lines.append(f"{'─' * w}")
    lines.append("  SECTION 5: RECOMMENDATIONS")
    lines.append(f"{'─' * w}")
    lines.append("""
  1. DATA COLLECTION (CRITICAL):
     The Firebase export is NOT suitable for evaluating the v2 pipeline:
       - v1 image measurements are dominated by default/placeholder values
         (115 records with width=9.8/ball=23.5/instep=24.1,
          158 records with ball=35.0/instep=35.0)
       - Manual measurements have systematic field confusion
         (arch height values of 18-25cm are impossible, likely instep girth)
       - Only ~40 records have non-default image values, and even those
         show suspiciously low variance

     ACTION: Collect a clean validation dataset of ≥30 patients:
       a. Trained measurer takes manual measurements with caliper/tape
       b. Same patient photographed with v2 pipeline protocol (6 views + ref card)
       c. Both recorded in a dedicated validation spreadsheet (not the app)
       d. Double-check each manual entry for plausibility before saving

  2. EVALUATION PROTOCOL:
     Once clean data is available, re-run this script with --preds pointing
     to the v2 pipeline output directory. The script computes MAE, RMSE,
     Bland-Altman LoA, ICC, and percentile errors automatically.

  3. ACCEPTANCE CRITERIA:
     Before production deployment, demonstrate on the validation set:
       - Foot length MAE < 5 mm, P95 < 10 mm
       - Forefoot width MAE < 3 mm, P95 < 6 mm
       - Ball girth MAE < 5 mm, P95 < 10 mm (if using girth)
       - ICC > 0.90 for all primary measurements
       - No systematic bias > 2 mm (Bland-Altman)
""")

    lines.append("=" * w)
    return "\n".join(lines)


# ─── JSON export for programmatic use ───────────────────────────────

def export_metrics_json(
    paired_data: dict,
    paired_stats: dict,
    pipeline_data: Optional[dict] = None,
) -> dict:
    """Export all metrics as a JSON-serialisable dict."""
    out = {"data_quality": paired_stats, "v1_vs_manual": {}, "v2_vs_manual": {}}

    for field, d in paired_data.items():
        if len(d["image_cm"]) >= 2:
            img = np.array(d["image_cm"])
            man = np.array(d["manual_cm"])
            out["v1_vs_manual"][field] = compute_metrics(img, man)

    if pipeline_data:
        for field, d in pipeline_data.items():
            if len(d["pipeline_cm"]) >= 2:
                pred = np.array(d["pipeline_cm"])
                man = np.array(d["manual_cm"])
                out["v2_vs_manual"][field] = compute_metrics(pred, man)

    return out


# ─── CLI ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate foot measurement pipeline against manual ground truth."
    )
    parser.add_argument(
        "--db", required=True,
        help="Path to Firebase export JSON (lepra-project-...-export.json)"
    )
    parser.add_argument(
        "--preds",
        help="Path to directory of v2 pipeline prediction JSONs (optional)"
    )
    parser.add_argument(
        "-o", "--output",
        help="Write report to file instead of stdout"
    )
    parser.add_argument(
        "--json",
        help="Export metrics as JSON to this path"
    )
    args = parser.parse_args()

    # Load data
    print(f"Loading database from {args.db}...")
    db = load_firebase_db(args.db)

    # Extract paired v1 image vs manual
    paired_data, paired_stats = extract_paired_data(db)

    # Optionally load v2 pipeline predictions
    pipeline_data = None
    pipeline_stats = None
    if args.preds:
        print(f"Loading v2 predictions from {args.preds}...")
        pipeline_data, pipeline_stats = load_pipeline_predictions(args.preds, db)

    # Generate report
    report = format_report(args.db, paired_data, paired_stats, pipeline_data, pipeline_stats)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(report)

    # Optionally export JSON
    if args.json:
        metrics = export_metrics_json(paired_data, paired_stats, pipeline_data)
        Path(args.json).write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        print(f"Metrics JSON written to {args.json}")


if __name__ == "__main__":
    main()
