"""
cloud_storage.py — Firebase Firestore + Firebase Storage integration.

Environment variables:
  FIREBASE_CREDENTIALS      JSON string or path to service-account .json file
  FIREBASE_STORAGE_BUCKET   e.g. lepra-trial.appspot.com

Every public function is safe to call when credentials are absent or
when uploads fail — it logs a warning and returns a safe default.
Local file writes in live_app.py are never affected.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("cloud_storage")

# ── Firebase (Firestore + Storage) ────────────────────────────────────────────

_firebase_app       = None
_firestore_db       = None
_storage_bucket     = None
_firebase_lock      = threading.Lock()
_firebase_init_done = False


def _init_firebase() -> bool:
    """Lazy-initialize Firebase Admin SDK (Firestore + Storage). Returns True if successful."""
    global _firebase_app, _firestore_db, _storage_bucket, _firebase_init_done
    with _firebase_lock:
        if _firebase_init_done:
            return _firestore_db is not None
        _firebase_init_done = True

        creds_env = os.environ.get("FIREBASE_CREDENTIALS", "").strip()
        if not creds_env:
            logger.info("[cloud_storage] FIREBASE_CREDENTIALS not set — Firebase disabled")
            return False

        bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET", "").strip()

        try:
            import firebase_admin
            from firebase_admin import credentials, firestore, storage

            # Accept either a raw JSON string or a file path
            if creds_env.startswith("{"):
                tmp = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".json", delete=False, encoding="utf-8"
                )
                tmp.write(creds_env)
                tmp.flush()
                tmp.close()
                cred = credentials.Certificate(tmp.name)
            else:
                cred = credentials.Certificate(creds_env)

            options = {"storageBucket": bucket_name} if bucket_name else {}
            _firebase_app = firebase_admin.initialize_app(cred, options)
            _firestore_db = firestore.client()

            if bucket_name:
                _storage_bucket = storage.bucket()
                logger.info(
                    "[cloud_storage] Firebase initialized OK — Firestore + Storage (%s)",
                    bucket_name,
                )
            else:
                logger.info(
                    "[cloud_storage] Firebase initialized OK — Firestore only "
                    "(set FIREBASE_STORAGE_BUCKET to enable image uploads)"
                )
            return True
        except Exception as exc:
            logger.warning("[cloud_storage] Firebase init failed: %s", exc)
            return False


def _get_db():
    """Return Firestore client, or None if not configured / failed."""
    if not _firebase_init_done:
        _init_firebase()
    return _firestore_db


def _get_bucket():
    """Return Firebase Storage bucket, or None if not configured / failed."""
    if not _firebase_init_done:
        _init_firebase()
    return _storage_bucket


# ── Internal helpers ──────────────────────────────────────────────────────────

def _upload_one_storage(local_path: str, blob_name: str) -> Optional[str]:
    """
    Upload a single file to Firebase Storage.
    Returns the public download URL or None on failure.
    """
    bucket = _get_bucket()
    if bucket is None:
        return None
    try:
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(local_path)
        blob.make_public()
        return blob.public_url
    except Exception as exc:
        logger.warning("[cloud_storage] Storage upload failed for %s: %s", local_path, exc)
        return None


def _format_history_entry(doc_data: dict) -> dict:
    """Convert a Firestore run document to the shape expected by /api/history."""
    compact = doc_data.get("measurements_compact", {})
    left  = compact.get("left",  {})
    right = compact.get("right", {})
    fl = left.get("foot_length_mm",  {})
    fr = right.get("foot_length_mm", {})

    def _fmt(v) -> str:
        if isinstance(v, dict):
            val = v.get("value_mm")
            return f"{val / 10:.2f} cm" if val is not None else "--"
        if isinstance(v, (int, float)):
            return f"{v / 10:.2f} cm"
        return "--"

    submitted = doc_data.get("submitted_at", "")
    date = submitted[:10] if submitted else ""

    return {
        "run_id":            doc_data.get("run_id", ""),
        "patient_id":        doc_data.get("patient_id", ""),
        "patient_name":      doc_data.get("patient_name", ""),
        "date":              date,
        "quality":           doc_data.get("overall_quality", "unknown"),
        "foot_length_left":  _fmt(fl),
        "foot_length_right": _fmt(fr),
        "json_url":          doc_data.get("local_compact_url", ""),
        "submitted_by":      doc_data.get("submitted_by", ""),
    }


# ── Public API ────────────────────────────────────────────────────────────────

def save_run_to_firestore(
    run_id: str,
    patient_meta: dict,
    compact: dict,
    full: dict,
    overall_quality: str,
    duration_secs: Optional[float],
) -> bool:
    """
    Write (or merge) a run document to Firestore runs/{run_id}.
    Returns True on success, False on failure.
    """
    db = _get_db()
    if db is None:
        return False

    try:
        pid = patient_meta.get("patient_id", run_id)
        doc = {
            "run_id":               run_id,
            "created_at":           patient_meta.get("submitted_at", ""),
            "overall_quality":      overall_quality,
            "duration_secs":        duration_secs,
            # Patient demographics
            "patient_id":           patient_meta.get("patient_id", ""),
            "patient_name":         patient_meta.get("patient_name", ""),
            "age":                  patient_meta.get("age", ""),
            "gender":               patient_meta.get("gender", ""),
            "diabetes":             patient_meta.get("diabetes", ""),
            "amputated_toes":       patient_meta.get("amputated_toes", ""),
            "abha_id":              patient_meta.get("abha_id", ""),
            "aadhar_id":            patient_meta.get("aadhar_id", ""),
            "who_grade":            patient_meta.get("who_grade", ""),
            "district":             patient_meta.get("district", ""),
            "village":              patient_meta.get("village", ""),
            "capture_center":       patient_meta.get("capture_center", ""),
            "referring_doctor":     patient_meta.get("referring_doctor", ""),
            "exam_date":            patient_meta.get("exam_date", ""),
            "clinical_notes":       patient_meta.get("clinical_notes", ""),
            "phone":                patient_meta.get("phone", ""),
            "captured_by":          patient_meta.get("captured_by", ""),
            "reference_type":       patient_meta.get("reference_type", ""),
            "submitted_by":         patient_meta.get("submitted_by", ""),
            "submitted_by_role":    patient_meta.get("submitted_by_role", ""),
            "submitted_at":         patient_meta.get("submitted_at", ""),
            "manual_measurements":  patient_meta.get("manual_measurements", {}),
            # Measurements
            "measurements_compact":   compact,
            "measurements_full_json": json.dumps(full),
            # Local fallback URLs
            "local_compact_url": f"/runs/{run_id}/output/{pid}_measurements.json",
            "local_full_url":    f"/runs/{run_id}/output/{pid}_measurements_full.json",
        }
        db.collection("runs").document(run_id).set(doc, merge=True)
        logger.info("[cloud_storage] Firestore run saved: %s", run_id)
        return True
    except Exception as exc:
        logger.warning("[cloud_storage] Firestore save failed for %s: %s", run_id, exc)
        return False


def upload_input_images_to_storage(
    run_id: str,
    image_paths: Dict[str, str],
) -> Dict[str, str]:
    """
    Upload the 6 input foot images to Firebase Storage under
    lepra-foot/input/{run_id}/{key}.
    image_paths: {"left_plantar": "/abs/path/left_plantar.jpeg", ...}
    Returns dict of {key: public_url} for successfully uploaded images.
    """
    if _get_bucket() is None:
        return {}

    urls: Dict[str, str] = {}
    for key, local_path in image_paths.items():
        if not local_path or not Path(local_path).exists():
            continue
        ext = Path(local_path).suffix
        blob_name = f"lepra-foot/input/{run_id}/{key}{ext}"
        url = _upload_one_storage(local_path, blob_name)
        if url:
            urls[key] = url

    if urls:
        logger.info("[cloud_storage] Uploaded %d input images for %s", len(urls), run_id)
    return urls


def upload_viz_images_to_storage(
    run_id: str,
    viz_paths: Dict[str, str],
) -> Dict[str, str]:
    """
    Upload visualization images to Firebase Storage under
    lepra-foot/viz/{run_id}/{key}.
    viz_paths: {"left_plantar_seg": "/abs/path/..._seg.jpg", ...}
    Returns dict of {key: public_url}.
    """
    if _get_bucket() is None:
        return {}

    urls: Dict[str, str] = {}
    for key, local_path in viz_paths.items():
        if not local_path or not Path(local_path).exists():
            continue
        blob_name = f"lepra-foot/viz/{run_id}/{key}.jpg"
        url = _upload_one_storage(local_path, blob_name)
        if url:
            urls[key] = url

    if urls:
        logger.info("[cloud_storage] Uploaded %d viz images for %s", len(urls), run_id)
    return urls


def update_run_storage_urls(
    run_id: str,
    storage_input: Dict[str, str],
    storage_seg:   Dict[str, str],
    storage_lm:    Dict[str, str],
    storage_viz:   Dict[str, str],
) -> bool:
    """
    Merge Firebase Storage URL maps into Firestore runs/{run_id}.
    Uses set(..., merge=True) — safe to call before or after save_run_to_firestore.
    Only non-empty dicts are written.
    """
    db = _get_db()
    if db is None:
        return False

    update_data: dict = {}
    if storage_input:
        update_data["storage_input"] = storage_input
    if storage_seg:
        update_data["storage_seg"] = storage_seg
    if storage_lm:
        update_data["storage_lm"] = storage_lm
    if storage_viz:
        update_data["storage_viz"] = storage_viz

    if not update_data:
        return True

    try:
        db.collection("runs").document(run_id).set(update_data, merge=True)
        logger.info("[cloud_storage] Storage URLs updated in Firestore for %s", run_id)
        return True
    except Exception as exc:
        logger.warning("[cloud_storage] Firestore URL update failed for %s: %s", run_id, exc)
        return False


# ── Session management ───────────────────────────────────────────────────────

SESSION_TTL_HOURS = 8


def save_session(token: str, data: dict) -> None:
    """
    Persist a session to Firestore sessions/{token}.
    data must include: username, role, name, center, created_at, expires_at
    Never raises.
    """
    db = _get_db()
    if db is None:
        return
    try:
        db.collection("sessions").document(token).set(data)
    except Exception as exc:
        logger.warning("[cloud_storage] save_session failed: %s", exc)


def get_session(token: str) -> Optional[dict]:
    """
    Fetch a session from Firestore. Returns None if missing, expired, or unavailable.
    Deletes the document if expired.
    """
    db = _get_db()
    if db is None:
        return None
    try:
        doc = db.collection("sessions").document(token).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        if data.get("expires_at", "") < datetime.now().isoformat():
            delete_session(token)
            return None
        return data
    except Exception as exc:
        logger.warning("[cloud_storage] get_session failed: %s", exc)
        return None


def delete_session(token: str) -> None:
    """Remove a session from Firestore. Never raises."""
    db = _get_db()
    if db is None:
        return
    try:
        db.collection("sessions").document(token).delete()
    except Exception as exc:
        logger.warning("[cloud_storage] delete_session failed: %s", exc)


# ── User management ──────────────────────────────────────────────────────────

def get_user_from_firestore(username: str) -> Optional[dict]:
    """
    Fetch a single user document from Firestore users/{username}.
    Returns the user dict, or None if not found or Firestore unavailable.
    """
    db = _get_db()
    if db is None:
        return None
    try:
        doc = db.collection("users").document(username).get()
        return doc.to_dict() if doc.exists else None
    except Exception as exc:
        logger.warning("[cloud_storage] Firestore get_user failed for %s: %s", username, exc)
        return None


def save_user_to_firestore(username: str, user_data: dict) -> bool:
    """
    Write (or overwrite) a user document to Firestore users/{username}.
    Returns True on success, False on failure.
    """
    db = _get_db()
    if db is None:
        return False
    try:
        db.collection("users").document(username).set(user_data)
        logger.info("[cloud_storage] Firestore user saved: %s", username)
        return True
    except Exception as exc:
        logger.warning("[cloud_storage] Firestore save_user failed for %s: %s", username, exc)
        return False


def update_user_in_firestore(username: str, fields: dict) -> bool:
    """
    Merge specific fields into an existing Firestore users/{username} document.
    Returns True on success, False on failure.
    """
    db = _get_db()
    if db is None:
        return False
    try:
        db.collection("users").document(username).set(fields, merge=True)
        return True
    except Exception as exc:
        logger.warning("[cloud_storage] Firestore update_user failed for %s: %s", username, exc)
        return False


def get_all_users_from_firestore() -> Optional[dict]:
    """
    Fetch all user documents from Firestore users collection.
    Returns dict of {username: user_data}, or None if Firestore unavailable.
    """
    db = _get_db()
    if db is None:
        return None
    try:
        docs = db.collection("users").stream()
        return {doc.id: doc.to_dict() for doc in docs}
    except Exception as exc:
        logger.warning("[cloud_storage] Firestore get_all_users failed: %s", exc)
        return None


def firestore_available() -> bool:
    """Returns True if Firestore is configured and reachable."""
    return _get_db() is not None


def log_error(run_id: str, error_msg: str, traceback_str: str = "") -> None:
    """
    Write a pipeline error to Firestore errors collection for remote visibility.
    Never raises — fire and forget.
    """
    db = _get_db()
    if db is None:
        return
    try:
        doc_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{run_id}"
        db.collection("errors").document(doc_id).set({
            "run_id":       run_id,
            "error":        error_msg,
            "traceback":    traceback_str,
            "created_at":   datetime.now().isoformat(),
        })
    except Exception as exc:
        logger.warning("[cloud_storage] Failed to log error to Firestore: %s", exc)


def get_run_from_firestore(run_id: str) -> Optional[dict]:
    """
    Fetch a single run document from Firestore by run_id.
    Returns the raw document dict or None.
    """
    db = _get_db()
    if db is None:
        return None
    try:
        doc = db.collection("runs").document(run_id).get()
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception as exc:
        logger.warning("[cloud_storage] Firestore get_run failed for %s: %s", run_id, exc)
        return None


def get_all_runs_from_firestore(
    role: str,
    username: str,
) -> Optional[List[dict]]:
    """
    Fetch all run documents from Firestore, sorted by created_at descending.
    Agents see only their own submissions; admins see all.
    Returns None if Firestore is unavailable (caller falls back to local scan).
    Returns [] if Firestore is available but has no matching runs.
    """
    db = _get_db()
    if db is None:
        return None

    try:
        col = db.collection("runs")
        if role == "agent":
            query = col.where("submitted_by", "==", username).order_by(
                "created_at", direction="DESCENDING"
            )
        else:
            query = col.order_by("created_at", direction="DESCENDING")

        docs = query.stream()
        entries = [_format_history_entry(doc.to_dict()) for doc in docs]
        return entries
    except Exception as exc:
        logger.warning("[cloud_storage] Firestore history query failed: %s", exc)
        return None
