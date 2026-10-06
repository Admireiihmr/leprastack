from __future__ import annotations

import base64
import csv
import json
import logging
import re
import shutil
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple
from uuid import uuid4

from datetime import timedelta
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import hashlib
import hmac as _hmac
import os

from foot_pipeline import FootPipeline
import cloud_storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("live_app")

# Path prefix this app is served under. Empty when it owns the origin (Docker /
# HF Spaces); set to "/dimple-app" when the Next.js portal reverse-proxies it
# into an iframe, so that root-absolute links in the HTML below resolve to this
# app instead of to the portal's own /signup and / pages.
BASE_PATH = os.environ.get("DIMPLE_BASE_PATH", "").rstrip("/")


def _with_base(html: str) -> str:
    """Substitute the {{BASE}} placeholder in a static HTML page."""
    return html.replace("{{BASE}}", BASE_PATH)



def _hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${h}"


def _verify_password(password: str, stored: str) -> bool:
    if "$" not in stored:
        return False
    salt, h = stored.split("$", 1)
    return _hmac.compare_digest(
        hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex(),
        h,
    )


APP_TITLE = "Lepra 2.0"

# Use HF persistent storage if available, else local
_HF_PERSISTENT = Path("/data")
print(f"[STORAGE DEBUG] /data exists={_HF_PERSISTENT.exists()}, is_dir={_HF_PERSISTENT.is_dir() if _HF_PERSISTENT.exists() else 'N/A'}, writable={os.access(_HF_PERSISTENT, os.W_OK) if _HF_PERSISTENT.exists() else 'N/A'}")
if _HF_PERSISTENT.exists() and _HF_PERSISTENT.is_dir() and os.access(_HF_PERSISTENT, os.W_OK):
    RUNS_DIR = _HF_PERSISTENT / "web_runs"
    USERS_FILE = _HF_PERSISTENT / "users.json"
    print(f"[STORAGE] Using PERSISTENT storage: {RUNS_DIR}")
elif Path("/tmp").exists():
    # Docker /app is read-only; use /tmp as fallback
    RUNS_DIR = Path("/tmp/web_runs")
    USERS_FILE = Path("/tmp/users.json")
    print(f"[STORAGE] Using TEMPORARY storage: {RUNS_DIR} (data lost on restart!)")
else:
    RUNS_DIR = Path("web_runs")
    USERS_FILE = Path("users.json")
    print(f"[STORAGE] Using LOCAL storage: {RUNS_DIR}")
RUNS_DIR.mkdir(parents=True, exist_ok=True)

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title=APP_TITLE)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.mount("/runs", StaticFiles(directory=str(RUNS_DIR)), name="runs")

# Sample images directory for upload help popups
SAMPLES_DIR = Path("samples")
SAMPLES_DIR.mkdir(exist_ok=True)
app.mount("/samples", StaticFiles(directory=str(SAMPLES_DIR)), name="samples")

PIPELINE_LOCK = threading.Lock()

# ── Singleton models for /api/validate-view ──────────────────────────────────
_validate_seg_model  = None
_validate_card_model = None
_validate_model_lock = threading.Lock()


def _get_validate_seg_model():
    global _validate_seg_model
    with _validate_model_lock:
        if _validate_seg_model is None:
            try:
                from foot_pipeline import _load_unet, _DEFAULT_UNET_PATH
                _validate_seg_model = _load_unet(_DEFAULT_UNET_PATH)
            except Exception as e:
                import logging
                logging.getLogger("live_app").warning("validate seg model load failed: %s", e)
    return _validate_seg_model


def _get_validate_card_model():
    global _validate_card_model
    with _validate_model_lock:
        if _validate_card_model is None:
            try:
                from ultralytics import YOLO
                _validate_card_model = YOLO("checkpoints/card_detector.pt")
            except Exception as e:
                import logging
                logging.getLogger("live_app").warning("validate card model load failed: %s", e)
    return _validate_card_model


# job_store holds per-run state:
#   status   : "processing" | "complete" | "error"
#   percent  : 0-100
#   stage    : current stage name
#   view     : current view key (or None)
#   payload  : final result dict (when complete)
#   error    : error message string (when error)
_job_store: Dict[str, dict] = {}
_job_lock  = threading.Lock()

# Simple in-memory session store
_sessions: Dict[str, dict] = {}

# ── User store (Firestore-first, local file fallback) ──
_users_lock = threading.Lock()


def _load_users() -> dict:
    # Try Firestore first
    fs_users = cloud_storage.get_all_users_from_firestore()
    if fs_users is not None:
        return fs_users
    # Fallback: local file
    with _users_lock:
        if USERS_FILE.exists():
            return json.loads(USERS_FILE.read_text(encoding="utf-8"))
        return {}


def _save_users(users: dict) -> None:
    # Always write local file as backup
    with _users_lock:
        USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")
    # Mirror entire users dict to Firestore
    for username, user_data in users.items():
        cloud_storage.save_user_to_firestore(username, user_data)


def _seed_admin():
    # Check Firestore first, then local file
    existing = cloud_storage.get_user_from_firestore("admin")
    if existing is None:
        existing = _load_users().get("admin")
    if existing:
        return
    admin_data = {
        "password_hash":      _hash_password("admin"),
        "role":               "admin",
        "name":               "Administrator",
        "phone":              "",
        "email":              "",
        "center":             "",
        "state":              "",
        "created_at":         datetime.now().isoformat(),
        "approved":           True,
        "must_change_password": True,
    }
    cloud_storage.save_user_to_firestore("admin", admin_data)
    # Mirror to local file as backup
    users = _load_users()
    users["admin"] = admin_data
    with _users_lock:
        USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")


_seed_admin()

VIEW_FIELDS = (
    ("left", "plantar"),
    ("left", "dorsal"),
    ("left", "medial"),
    ("right", "plantar"),
    ("right", "dorsal"),
    ("right", "medial"),
)
VIEW_LABELS = {
    "left_plantar": "Left plantar",
    "left_dorsal": "Left dorsal",
    "left_medial": "Left medial",
    "right_plantar": "Right plantar",
    "right_dorsal": "Right dorsal",
    "right_medial": "Right medial",
}


def _get_session(request: Request) -> dict | None:
    token = request.cookies.get("session")
    if not token:
        return None
    # Try Firestore first (survives restarts)
    fs_session = cloud_storage.get_session(token)
    if fs_session:
        _sessions[token] = fs_session  # refresh in-memory cache
        return fs_session
    # Fallback: in-memory (check expiry)
    data = _sessions.get(token)
    if data:
        if data.get("expires_at", "") < datetime.now().isoformat():
            del _sessions[token]
            return None
        return data
    return None


# ─────────────────────────────────────────────────────────────
# Login page HTML
# ─────────────────────────────────────────────────────────────
HTML_LOGIN = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LEPRA &mdash; Sign In</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body { min-height: 100%; overflow-x: hidden; }
    body {
      font-family: 'Inter', sans-serif;
      min-height: 100vh;
      width: 100%;
      display: flex;
      flex-direction: column;
    }

    /* ── Full-bleed background photo + wash ── */
    .login-page {
      position: relative;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      background-image: url('/samples/login-bg.jpg');
      background-size: cover;
      background-position: center;
    }
    .login-overlay {
      position: absolute;
      inset: 0;
      background: rgba(255,255,255,0.55);
      pointer-events: none;
    }

    /* ── Glass header ── */
    .login-header {
      position: sticky;
      top: 0;
      z-index: 30;
      border-bottom: 1px solid rgba(255,255,255,0.4);
      background: rgba(255,255,255,0.7);
      backdrop-filter: blur(10px);
    }
    .login-header-inner {
      width: 100%;
      padding: 0 10px;
      height: 64px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    .brand-mark-group { display: flex; align-items: center; gap: 10px; }
    .header-left { display: flex; align-items: center; gap: 10px; }
    .back-to-portal {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 32px;
      height: 32px;
      border-radius: 50%;
      border: 1px solid #d3deef;
      color: #6a7896;
      text-decoration: none;
      flex-shrink: 0;
      transition: color 0.15s, border-color 0.15s;
    }
    .back-to-portal:hover { color: #0f1d36; border-color: #9db4d8; }
    .header-divider { width: 1px; height: 24px; background: #d3deef; flex-shrink: 0; }
    .brand-mark {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 36px;
      height: 36px;
      border-radius: 12px;
      background: linear-gradient(135deg, #2563eb, #0ea5e9);
      color: #fff;
      font-size: 18px;
      box-shadow: 0 4px 12px -3px rgba(37,99,235,0.30);
    }
    .brand-title { font-weight: 800; font-size: 0.92rem; color: #0f1d36; letter-spacing: 0.02em; }
    .brand-subtitle { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.14em; color: #6a7896; }

    /* ── Main layout ── */
    .login-main {
      position: relative;
      z-index: 10;
      flex: 1;
      width: 100%;
      max-width: 1400px;
      margin: 0 auto;
      padding: 40px 24px 48px;
      display: flex;
      align-items: flex-start;
      justify-content: center;
    }
    .login-grid {
      width: 100%;
      max-width: 1200px;
      display: grid;
      grid-template-columns: 1fr;
      gap: 40px;
      align-items: start;
    }
    .login-hero { display: none; }
    .login-hero h1 { font-size: 2.6rem; font-weight: 800; color: #0f1d36; line-height: 1.15; letter-spacing: -0.01em; }
    .login-hero p { margin-top: 16px; font-size: 1rem; color: #3b4b6b; line-height: 1.6; max-width: 480px; }
    .login-features { margin-top: 32px; display: grid; grid-template-columns: 1fr 1fr; gap: 12px; max-width: 480px; }
    .feature-chip {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 12px;
      border-radius: 12px;
      background: rgba(255,255,255,0.65);
      backdrop-filter: blur(6px);
      border: 1px solid rgba(255,255,255,0.7);
      box-shadow: 0 1px 2px 0 rgba(30,58,138,0.06), 0 4px 12px -2px rgba(30,58,138,0.08);
      font-size: 0.78rem;
      font-weight: 600;
      color: #3b4b6b;
    }
    .feature-chip .fc-icon { color: #2563eb; flex-shrink: 0; }

    @media (min-width: 1024px) {
      .login-grid { grid-template-columns: 1fr 420px; gap: 64px; }
      .login-hero { display: block; }
      .login-main { align-items: center; }
    }

    /* ── Mobile app-style hero (full-bleed gradient, logo + headline
       overlaid, card pulled up over its bottom edge) ── */
    .login-mobile-hero {
      position: relative;
      overflow: hidden;
      padding: 28px 24px 56px;
      border-radius: 0 0 40px 40px;
      background: linear-gradient(160deg, #2563eb 0%, #0ea5e9 100%);
    }
    .login-mobile-hero::before,
    .login-mobile-hero::after {
      content: '';
      position: absolute;
      border-radius: 50%;
      background: rgba(255,255,255,0.1);
      filter: blur(30px);
    }
    .login-mobile-hero::before { width: 190px; height: 190px; top: -50px; right: -40px; }
    .login-mobile-hero::after { width: 220px; height: 220px; bottom: -70px; left: -50px; }
    .login-mobile-hero-dots { position: absolute; inset: 0; opacity: 0.12; }
    .login-mobile-hero-top { position: relative; z-index: 1; display: flex; align-items: center; gap: 10px; }
    .login-mobile-hero-mark {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 36px;
      height: 36px;
      border-radius: 12px;
      background: rgba(255,255,255,0.15);
      border: 1px solid rgba(255,255,255,0.25);
      color: #fff;
      font-size: 18px;
      flex-shrink: 0;
    }
    .login-mobile-hero-title { font-weight: 800; font-size: 0.92rem; color: #fff; letter-spacing: 0.02em; }
    .login-mobile-hero-subtitle { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.14em; color: rgba(255,255,255,0.7); }
    .login-mobile-hero h1 { position: relative; z-index: 1; margin-top: 26px; font-size: 1.6rem; font-weight: 800; color: #fff; line-height: 1.2; }
    .login-mobile-hero p { position: relative; z-index: 1; margin-top: 8px; font-size: 0.88rem; color: rgba(255,255,255,0.8); line-height: 1.5; max-width: 320px; }
    @media (max-width: 1023px) {
      .login-main { padding-top: 0; }
    }
    @media (min-width: 1024px) {
      .login-mobile-hero { display: none; }
    }

    .login-card-wrap { width: 100%; max-width: 420px; margin: 0 auto; }
    @media (max-width: 1023px) {
      .login-card-wrap { margin-top: -32px; position: relative; z-index: 1; }
    }
    .login-form {
      width: 100%;
      background: #fff;
      border: 1px solid #d3deef;
      border-radius: 12px;
      padding: 32px 32px 36px;
      box-shadow: 0 12px 32px -10px rgba(30,58,138,0.28), 0 4px 12px -4px rgba(15,23,42,0.10);
    }
    .login-form h1 {
      font-size: 1.5rem;
      font-weight: 800;
      color: #0f1d36;
      margin-bottom: 6px;
      letter-spacing: -0.01em;
      text-align: center;
    }
    .login-form .sub {
      font-size: 0.88rem;
      color: #6a7896;
      margin-bottom: 28px;
      line-height: 1.5;
      text-align: center;
    }
    .login-form .sub strong { color: #2563eb; font-weight: 700; }
    .login-form .field {
      margin-bottom: 20px;
    }
    .login-form .field input {
      width: 100%;
      padding: 12px 16px;
      border: 1px solid #d3deef;
      border-radius: 12px;
      font-family: 'Inter', sans-serif;
      font-size: 0.95rem;
      color: #0f1d36;
      background: #fff;
      transition: border-color 0.2s, box-shadow 0.2s;
    }
    .login-form .field input::placeholder { color: rgba(37,99,235,0.35); }
    .login-form .field input:focus {
      outline: none;
      border-color: #2563eb;
      box-shadow: 0 0 0 4px rgba(37,99,235,0.20);
    }
    .login-btn {
      width: 100%;
      padding: 14px;
      border: 0;
      border-radius: 12px;
      background: #2563eb;
      color: #fff;
      font-family: 'Inter', sans-serif;
      font-size: 1rem;
      font-weight: 700;
      cursor: pointer;
      transition: background 0.16s, transform 0.16s, box-shadow 0.16s;
      margin-top: 6px;
      letter-spacing: 0.02em;
      box-shadow: 0 4px 14px -4px rgba(37,99,235,0.30);
    }
    .login-btn:hover { background: #1d4ed8; transform: translateY(-1px); box-shadow: 0 12px 26px -8px rgba(37,99,235,0.30); }
    .login-btn:active { transform: scale(0.98); }
    .login-error {
      color: #dc2626;
      font-size: 0.85rem;
      font-weight: 600;
      margin-top: 14px;
      min-height: 20px;
      text-align: center;
    }
    .login-footer {
      margin-top: 32px;
      text-align: center;
      font-size: 0.82rem;
      color: #8294b5;
    }
    .login-lang {
      margin-top: 16px;
      text-align: center;
    }
    .login-lang select {
      padding: 6px 12px;
      border: 1px solid #d3deef;
      border-radius: 20px;
      font-family: 'Inter', sans-serif;
      font-size: 0.82rem;
      color: #6a7896;
      background: #fff;
      cursor: pointer;
    }

    /* ── Footer (matches the Lepra Stack portal shell this app is embedded in) ── */
    .site-footer-bar {
      position: relative;
      z-index: 10;
      border-top: 1px solid rgba(0,0,0,0.06);
      background: #fff;
    }
    .site-footer-inner {
      width: 100%;
      padding: 14px 10px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 10px 24px;
      font-size: 0.75rem;
      line-height: 1.5;
      color: #374151;
      opacity: 1;
    }
    .site-footer-inner strong { font-weight: 600; color: #1f2937; }
    .site-footer-inner a { color: #2563eb; font-weight: 600; text-decoration: none; }
    .site-footer-inner a:hover { text-decoration: underline; }
    .footer-partners { display: flex; align-items: center; gap: 12px; }
    .footer-partners-label { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.06em; color: #4b5563; white-space: nowrap; font-weight: 600; }
    .footer-logos { display: flex; align-items: center; gap: 12px; }
    .footer-dot { color: #d1d5db; font-weight: 700; }
    .footer-logos img { height: 28px; width: 80px; object-fit: contain; border-radius: 4px; opacity: 1; }
    @media (max-width: 640px) {
      .site-footer-inner { flex-direction: column; text-align: center; justify-content: center; }
      .footer-partners { flex-direction: column; gap: 8px; }
      .footer-logos { justify-content: center; flex-wrap: wrap; gap: 10px; }
      .footer-logos img { height: 24px; width: 64px; }
    }

    @media (max-width: 768px) {
      .login-header-inner { padding: 0 10px; }
      .login-main { padding: 0 12px 32px; }
    }
  </style>
</head>
<body>
  <div class="login-page">
    <div class="login-overlay"></div>

    <header class="login-header">
      <div class="login-header-inner">
        <div class="header-left">
          <a class="back-to-portal" href="/" title="Back to Lepra Stack" aria-label="Back to Lepra Stack">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5"></path><path d="M12 19l-7-7 7-7"></path></svg>
          </a>
          <span class="header-divider"></span>
          <div class="brand-mark-group">
            <span class="brand-mark">🦶</span>
            <div>
              <div class="brand-title">LEPRA</div>
              <div class="brand-subtitle" data-i18n="brand_subtitle">Foot Measurement System</div>
            </div>
          </div>
        </div>
        <div class="login-lang">
          <select id="login-lang-select" onchange="setLoginLang(this.value)">
            <option value="en">English</option>
            <option value="hi">हिन्दी</option>
            <option value="or">ଓଡ଼ିଆ</option>
            <option value="te">తెలుగు</option>
            <option value="mr">मराठी</option>
          </select>
        </div>
      </div>
    </header>

    <div class="login-mobile-hero">
      <svg class="login-mobile-hero-dots" preserveAspectRatio="none">
        <defs>
          <pattern id="dimple-dots" width="22" height="22" patternUnits="userSpaceOnUse">
            <circle cx="2" cy="2" r="1.6" fill="#fff"></circle>
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#dimple-dots)"></rect>
      </svg>
      <div class="login-mobile-hero-top">
        <span class="login-mobile-hero-mark">🦶</span>
        <div>
          <div class="login-mobile-hero-title">LEPRA</div>
          <div class="login-mobile-hero-subtitle" data-i18n="brand_subtitle">Foot Measurement System</div>
        </div>
      </div>
      <h1 data-i18n="hero_title">AI-assisted foot measurement for leprosy care.</h1>
      <p data-i18n="hero_desc">Capture, measure and track footwear fit in the field.</p>
    </div>

    <main class="login-main">
      <div class="login-grid">
        <div class="login-hero">
          <h1 data-i18n="hero_title">AI-assisted foot measurement for leprosy care.</h1>
          <p data-i18n="hero_desc">Capture, measure and track footwear fit in the field.</p>
          <div class="login-features">
            <div class="feature-chip"><span class="fc-icon">📏</span> <span data-i18n="feature_measurement">AI-assisted measurement</span></div>
            <div class="feature-chip"><span class="fc-icon">📈</span> <span data-i18n="feature_tracking">Track deformity progression</span></div>
            <div class="feature-chip"><span class="fc-icon">🌐</span> <span data-i18n="feature_multilang">Multi-language support</span></div>
            <div class="feature-chip"><span class="fc-icon">🔒</span> <span data-i18n="feature_secure">Secure patient records</span></div>
          </div>
        </div>

        <div class="login-card-wrap">
          <div class="login-form">
            <!-- Login section -->
            <div id="login-section">
              <h1 data-i18n="welcome_back">Welcome back!</h1>
              <p class="sub"><span data-i18n="sign_in_desc">Sign in to</span> <strong>LEPRA</strong> <span data-i18n="sign_in_desc2">Foot Measurement System.</span><br><span data-i18n="get_started">Get started with your assessment.</span></p>
              <form id="login-form">
                <div class="field">
                  <input type="text" name="username" data-i18n-ph="ph_username" placeholder="Username" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" required autofocus>
                </div>
                <div class="field" style="position:relative;">
                  <input type="password" name="password" id="login-pw" data-i18n-ph="ph_password" placeholder="Password" autocomplete="current-password" required style="padding-right:42px;">
                  <button type="button" class="pw-eye" data-target="login-pw" tabindex="-1" aria-label="Show password" style="position:absolute;right:8px;top:50%;transform:translateY(-50%);background:none;border:0;cursor:pointer;padding:6px;font-size:16px;color:#666;">👁</button>
                  <div class="caps-warn" data-for="login-pw" style="display:none;color:#c0392b;font-size:0.8rem;margin-top:4px;">⚠ Caps Lock is on</div>
                </div>
                <button class="login-btn" type="submit" data-i18n="login_btn">Login</button>
                <div class="login-error" id="login-error"></div>
              </form>
              <div class="login-footer" data-i18n="login_footer">Automated Foot Measurement System</div>
              <div style="margin-top:16px;text-align:center;font-size:0.88rem;">
                <span data-i18n="agent_register_prompt">Field agent?</span>
                <a href="{{BASE}}/signup" style="color:#2563eb;font-weight:700;text-decoration:none;" data-i18n="agent_register_link">Register here</a>
              </div>
            </div>
            <!-- Force password change section (shown after first login) -->
            <div id="change-pw-section" style="display:none;">
              <h1>Set New Password</h1>
              <p class="sub" style="margin-bottom:20px;">For security, please set a new password before continuing.</p>
              <form id="change-pw-form">
                <div class="field" style="position:relative;">
                  <input type="password" id="old-password" placeholder="Current password" required style="padding-right:42px;">
                  <button type="button" class="pw-eye" data-target="old-password" tabindex="-1" aria-label="Show password" style="position:absolute;right:8px;top:50%;transform:translateY(-50%);background:none;border:0;cursor:pointer;padding:6px;font-size:16px;color:#666;">👁</button>
                  <div class="caps-warn" data-for="old-password" style="display:none;color:#c0392b;font-size:0.8rem;margin-top:4px;">⚠ Caps Lock is on</div>
                </div>
                <div class="field" style="position:relative;">
                  <input type="password" id="new-password" placeholder="New password (min 8 characters)" required minlength="8" style="padding-right:42px;">
                  <button type="button" class="pw-eye" data-target="new-password" tabindex="-1" aria-label="Show password" style="position:absolute;right:8px;top:50%;transform:translateY(-50%);background:none;border:0;cursor:pointer;padding:6px;font-size:16px;color:#666;">👁</button>
                  <div class="caps-warn" data-for="new-password" style="display:none;color:#c0392b;font-size:0.8rem;margin-top:4px;">⚠ Caps Lock is on</div>
                </div>
                <div class="field" style="position:relative;">
                  <input type="password" id="new-password-confirm" placeholder="Confirm new password" required style="padding-right:42px;">
                  <button type="button" class="pw-eye" data-target="new-password-confirm" tabindex="-1" aria-label="Show password" style="position:absolute;right:8px;top:50%;transform:translateY(-50%);background:none;border:0;cursor:pointer;padding:6px;font-size:16px;color:#666;">👁</button>
                  <div class="caps-warn" data-for="new-password-confirm" style="display:none;color:#c0392b;font-size:0.8rem;margin-top:4px;">⚠ Caps Lock is on</div>
                </div>
                <button class="login-btn" type="submit">Set Password & Continue</button>
                <div class="login-error" id="change-pw-error"></div>
              </form>
            </div>
          </div>
        </div>
      </div>
    </main>

    <footer class="site-footer-bar">
      <div class="site-footer-inner">
        <div>&copy; DIMPLE &middot; <span data-i18n="footer_authorised">For authorised health workers only</span></div>
        <div class="footer-partners">
          <span class="footer-partners-label" data-i18n="footer_partnership">In partnership with</span>
          <div class="footer-logos">
            <a href="https://leprasociety.in/" target="_blank" rel="noopener noreferrer"><img src="/samples/lepra-logo.png" alt="LEPRA Society"></a>
            <span class="footer-dot" aria-hidden="true">&middot;</span>
            <img src="/samples/iihmr-logo-footer.png" alt="IIHMR Bangalore">
            <span class="footer-dot" aria-hidden="true">&middot;</span>
            <img src="/samples/kind-care-logo.jpeg" alt="Kind Care">
          </div>
        </div>
      </div>
    </footer>
  </div>
  <script>
    const LOGIN_T = {
      en: { welcome_back:"Welcome back!", sign_in_desc:"Sign in to", sign_in_desc2:"Foot Measurement System.", get_started:"Get started with your assessment.", ph_username:"Username", ph_password:"Password", login_btn:"Login", login_footer:"Automated Foot Measurement System", invalid_creds:"Invalid credentials.", conn_error:"Connection error. Please try again.", brand_subtitle:"Foot Measurement System", hero_title:"AI-assisted foot measurement for leprosy care.", hero_desc:"Capture, measure and track footwear fit in the field.", feature_measurement:"AI-assisted measurement", feature_tracking:"Track deformity progression", feature_multilang:"Multi-language support", feature_secure:"Secure patient records", footer_authorised:"For authorised health workers only", footer_partnership:"In partnership with" },
      hi: { welcome_back:"वापस स्वागत है!", sign_in_desc:"साइन इन करें", sign_in_desc2:"पैर माप प्रणाली।", get_started:"अपना मूल्यांकन शुरू करें।", ph_username:"उपयोगकर्ता नाम", ph_password:"पासवर्ड", login_btn:"लॉगिन", login_footer:"स्वचालित पैर माप प्रणाली", invalid_creds:"अमान्य क्रेडेंशियल।", conn_error:"कनेक्शन त्रुटि। कृपया पुन: प्रयास करें।", brand_subtitle:"पैर माप प्रणाली", hero_title:"कुष्ठ रोग देखभाल के लिए एआई-सहायित पैर माप।", hero_desc:"फील्ड में जूते की फिटिंग को कैप्चर करें, मापें और ट्रैक करें।", feature_measurement:"एआई-सहायित माप", feature_tracking:"विकृति की प्रगति को ट्रैक करें", feature_multilang:"बहु-भाषा समर्थन", feature_secure:"सुरक्षित रोगी रिकॉर्ड", footer_authorised:"केवल अधिकृत स्वास्थ्य कार्यकर्ताओं के लिए", footer_partnership:"इनके साथ साझेदारी में" },
      or: { welcome_back:"ସ୍ୱାଗତ!", sign_in_desc:"ସାଇନ୍ ଇନ୍ କରନ୍ତୁ", sign_in_desc2:"ପାଦ ମାପ ସିଷ୍ଟମ।", get_started:"ଆପଣଙ୍କ ମୂଲ୍ୟାଙ୍କନ ଆରମ୍ଭ କରନ୍ତୁ।", ph_username:"ଉପଯୋଗକାରୀ ନାମ", ph_password:"ପାସୱାର୍ଡ", login_btn:"ଲଗଇନ୍", login_footer:"ସ୍ୱୟଂଚାଳିତ ପାଦ ମାପ ସିଷ୍ଟମ", invalid_creds:"ଅବୈଧ ପରିଚୟପତ୍ର।", conn_error:"ସଂଯୋଗ ତ୍ରୁଟି। ଦୟାକରି ପୁନଃଚେଷ୍ଟା କରନ୍ତୁ।", brand_subtitle:"ପାଦ ମାପ ସିଷ୍ଟମ", hero_title:"କୁଷ୍ଠ ରୋଗ ଯତ୍ନ ପାଇଁ AI-ସହାୟତାପ୍ରାପ୍ତ ପାଦ ମାପ।", hero_desc:"କ୍ଷେତ୍ରରେ ଫୁଟ୍‌ୱେୟାର୍ ଫିଟିଂ କ୍ୟାପଚର୍, ମାପ ଏବଂ ଟ୍ରାକ୍ କରନ୍ତୁ।", feature_measurement:"AI-ସହାୟତାପ୍ରାପ୍ତ ମାପ", feature_tracking:"ବିକୃତି ଅଗ୍ରଗତି ଟ୍ରାକ୍ କରନ୍ତୁ", feature_multilang:"ବହୁ-ଭାଷା ସମର୍ଥନ", feature_secure:"ସୁରକ୍ଷିତ ରୋଗୀ ରେକର୍ଡ", footer_authorised:"କେବଳ ଅଧିକୃତ ସ୍ୱାସ୍ଥ୍ୟ କର୍ମୀଙ୍କ ପାଇଁ", footer_partnership:"ସହଭାଗିତାରେ" },
      te: { welcome_back:"తిరిగి స్వాగతం!", sign_in_desc:"సైన్ ఇన్ చేయండి", sign_in_desc2:"పాద కొలత వ్యవస్థ.", get_started:"మీ అంచనాను ప్రారంభించండి.", ph_username:"వినియోగదారు పేరు", ph_password:"పాస్‌వర్డ్", login_btn:"లాగిన్", login_footer:"ఆటోమేటెడ్ పాద కొలత వ్యవస్థ", invalid_creds:"చెల్లని ఆధారాలు.", conn_error:"కనెక్షన్ లోపం. దయచేసి మళ్ళీ ప్రయత్నించండి.", brand_subtitle:"పాద కొలత వ్యవస్థ", hero_title:"కుష్ఠు వ్యాధి సంరక్షణ కోసం AI-సహాయక పాద కొలత.", hero_desc:"ఫీల్డ్‌లో పాదరక్షల ఫిట్‌ని క్యాప్చర్ చేయండి, కొలవండి మరియు ట్రాక్ చేయండి.", feature_measurement:"AI-సహాయక కొలత", feature_tracking:"వైకల్యం పురోగతిని ట్రాక్ చేయండి", feature_multilang:"బహుళ-భాషా మద్దతు", feature_secure:"సురక్షిత రోగి రికార్డులు", footer_authorised:"అధీకృత ఆరోగ్య కార్యకర్తలకు మాత్రమే", footer_partnership:"వీరి భాగస్వామ్యంతో" },
      mr: { welcome_back:"पुन्हा स्वागत!", sign_in_desc:"साइन इन करा", sign_in_desc2:"पाय मोजमाप प्रणाली.", get_started:"तुमचे मूल्यांकन सुरू करा.", ph_username:"वापरकर्ता नाव", ph_password:"पासवर्ड", login_btn:"लॉगिन", login_footer:"स्वयंचलित पाय मोजमाप प्रणाली", invalid_creds:"अवैध क्रेडेन्शियल्स.", conn_error:"कनेक्शन त्रुटी. कृपया पुन्हा प्रयत्न करा.", brand_subtitle:"पाय मोजमाप प्रणाली", hero_title:"कुष्ठरोग काळजीसाठी एआय-सहाय्यित पाय मोजमाप.", hero_desc:"फील्डमध्ये पादत्राणांची फिटिंग कॅप्चर करा, मोजा आणि ट्रॅक करा.", feature_measurement:"एआय-सहाय्यित मोजमाप", feature_tracking:"विकृतीची प्रगती ट्रॅक करा", feature_multilang:"बहु-भाषा समर्थन", feature_secure:"सुरक्षित रुग्ण नोंदी", footer_authorised:"केवळ अधिकृत आरोग्य कर्मचाऱ्यांसाठी", footer_partnership:"यांच्या भागीदारीत" }
    };
    function setLoginLang(lang) {
      document.querySelectorAll('[data-i18n]').forEach(el => {
        const k = el.getAttribute('data-i18n');
        if (LOGIN_T[lang] && LOGIN_T[lang][k]) el.textContent = LOGIN_T[lang][k];
      });
      document.querySelectorAll('[data-i18n-ph]').forEach(el => {
        const k = el.getAttribute('data-i18n-ph');
        if (LOGIN_T[lang] && LOGIN_T[lang][k]) el.placeholder = LOGIN_T[lang][k];
      });
      localStorage.setItem('lepra-lang', lang);
      document.getElementById('login-lang-select').value = lang;
    }
    (function(){ const s = localStorage.getItem('lepra-lang'); if (s && s !== 'en') setLoginLang(s); })();

    // Eye toggle + caps-lock warning for all .pw-eye buttons / .caps-warn fields.
    document.querySelectorAll('.pw-eye').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var inp = document.getElementById(btn.getAttribute('data-target'));
        if (!inp) return;
        var showing = inp.type === 'text';
        inp.type = showing ? 'password' : 'text';
        btn.textContent = showing ? '👁' : '🙈';
        btn.setAttribute('aria-label', showing ? 'Show password' : 'Hide password');
      });
    });
    document.querySelectorAll('.caps-warn').forEach(function(warn) {
      var inp = document.getElementById(warn.getAttribute('data-for'));
      if (!inp) return;
      function check(e) {
        var on = e.getModifierState && e.getModifierState('CapsLock');
        warn.style.display = on ? 'block' : 'none';
      }
      inp.addEventListener('keydown', check);
      inp.addEventListener('keyup', check);
      inp.addEventListener('blur', function() { warn.style.display = 'none'; });
    });

    var _isLoggingIn = false;
    document.getElementById("login-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      if (_isLoggingIn) return;
      _isLoggingIn = true;
      const errEl = document.getElementById("login-error");
      errEl.textContent = "";
      const fd = new FormData(e.target);
      const lang = localStorage.getItem('lepra-lang') || 'en';
      try {
        const r = await fetch("/api/login", { method: "POST", body: fd });
        const d = await r.json();
        if (r.ok) {
          if (d.must_change_password) {
            document.getElementById("login-section").style.display = "none";
            document.getElementById("change-pw-section").style.display = "";
          } else {
            window.location.reload();
            return; // Skip resetting _isLoggingIn — page is reloading.
          }
        } else {
          errEl.textContent = (LOGIN_T[lang] && LOGIN_T[lang].invalid_creds) || d.detail || "Invalid credentials.";
        }
      } catch(e) {
        errEl.textContent = (LOGIN_T[lang] && LOGIN_T[lang].conn_error) || "Connection error. Please try again.";
      }
      _isLoggingIn = false;
    });

    document.getElementById("change-pw-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const errEl = document.getElementById("change-pw-error");
      errEl.textContent = "";
      const np = document.getElementById("new-password").value;
      const nc = document.getElementById("new-password-confirm").value;
      if (np !== nc) { errEl.textContent = "Passwords do not match."; return; }
      const fd = new FormData();
      fd.append("old_password", document.getElementById("old-password").value);
      fd.append("new_password", np);
      try {
        const r = await fetch("/api/change-password", { method: "POST", body: fd });
        const d = await r.json();
        if (r.ok) { window.location.reload(); }
        else { errEl.textContent = d.detail || "Failed to change password."; }
      } catch(e) { errEl.textContent = "Connection error."; }
    });
  </script>
</body>
</html>
"""

# ─────────────────────────────────────────────────────────────
# Signup page HTML
# ─────────────────────────────────────────────────────────────
HTML_SIGNUP = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LEPRA &mdash; Agent Registration</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body { min-height: 100%; overflow-x: hidden; }
    body { font-family: 'Inter', sans-serif; width: 100%; }

    .login-page {
      position: relative;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      background-image: url('/samples/login-bg.jpg');
      background-size: cover;
      background-position: center;
    }
    .login-overlay { position: absolute; inset: 0; background: rgba(255,255,255,0.55); pointer-events: none; }

    .login-header {
      position: sticky;
      top: 0;
      z-index: 30;
      border-bottom: 1px solid rgba(255,255,255,0.4);
      background: rgba(255,255,255,0.7);
      backdrop-filter: blur(10px);
    }
    .login-header-inner {
      width: 100%; padding: 0 10px; height: 64px;
      display: flex; align-items: center; justify-content: space-between; gap: 16px;
    }
    .brand-mark-group { display: flex; align-items: center; gap: 10px; }
    .header-left { display: flex; align-items: center; gap: 10px; }
    .back-to-portal {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 32px;
      height: 32px;
      border-radius: 50%;
      border: 1px solid #d3deef;
      color: #6a7896;
      text-decoration: none;
      flex-shrink: 0;
      transition: color 0.15s, border-color 0.15s;
    }
    .back-to-portal:hover { color: #0f1d36; border-color: #9db4d8; }
    .header-divider { width: 1px; height: 24px; background: #d3deef; flex-shrink: 0; }
    .brand-mark {
      display: inline-flex; align-items: center; justify-content: center;
      width: 36px; height: 36px; border-radius: 12px;
      background: linear-gradient(135deg, #2563eb, #0ea5e9); color: #fff; font-size: 18px;
      box-shadow: 0 4px 12px -3px rgba(37,99,235,0.30);
    }
    .brand-title { font-weight: 800; font-size: 0.92rem; color: #0f1d36; letter-spacing: 0.02em; }
    .brand-subtitle { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.14em; color: #6a7896; }

    .login-main {
      position: relative; z-index: 10; flex: 1; width: 100%;
      display: flex; align-items: center; justify-content: center; padding: 32px 24px;
    }

    .site-footer-bar {
      position: relative;
      z-index: 10;
      border-top: 1px solid rgba(0,0,0,0.06);
      background: #fff;
    }
    .site-footer-inner {
      width: 100%;
      padding: 14px 10px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 10px 24px;
      font-size: 0.75rem;
      line-height: 1.5;
      color: #374151;
      opacity: 1;
    }
    .site-footer-inner strong { font-weight: 600; color: #1f2937; }
    .site-footer-inner a { color: #2563eb; font-weight: 600; text-decoration: none; }
    .site-footer-inner a:hover { text-decoration: underline; }
    .footer-partners { display: flex; align-items: center; gap: 12px; }
    .footer-partners-label { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.06em; color: #4b5563; white-space: nowrap; font-weight: 600; }
    .footer-logos { display: flex; align-items: center; gap: 12px; }
    .footer-dot { color: #d1d5db; font-weight: 700; }
    .footer-logos img { height: 28px; width: 80px; object-fit: contain; border-radius: 4px; opacity: 1; }
    @media (max-width: 640px) {
      .site-footer-inner { flex-direction: column; text-align: center; justify-content: center; }
      .footer-partners { flex-direction: column; gap: 8px; }
      .footer-logos { justify-content: center; flex-wrap: wrap; gap: 10px; }
      .footer-logos img { height: 24px; width: 64px; }
    }

    .signup-card { width: 100%; max-width: 480px; background: #fff; border: 1px solid #d3deef; border-radius: 12px; padding: 40px 36px; box-shadow: 0 12px 32px -10px rgba(30,58,138,0.28), 0 4px 12px -4px rgba(15,23,42,0.10); }
    .signup-card h1 { font-size: 1.6rem; font-weight: 900; color: #0f1d36; margin-bottom: 4px; }
    .signup-card .sub { font-size: 0.88rem; color: #6a7896; margin-bottom: 28px; }
    .signup-card .sub strong { color: #2563eb; font-weight: 700; }
    .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 14px; }
    .form-row.full { grid-template-columns: 1fr; }
    .form-row label { font-size: 0.82rem; font-weight: 700; color: #6a7896; margin-bottom: 4px; display: block; }
    .form-row input, .form-row select { width: 100%; padding: 11px 16px; border: 1px solid #d3deef; border-radius: 12px; font-family: 'Inter', sans-serif; font-size: 0.9rem; color: #0f1d36; background: #fff; }
    .form-row input:focus, .form-row select:focus { outline: none; border-color: #2563eb; box-shadow: 0 0 0 4px rgba(37,99,235,0.20); }
    .signup-btn { width: 100%; padding: 13px; border: 0; border-radius: 12px; background: #2563eb; color: #fff; font-family: 'Inter', sans-serif; font-size: 1rem; font-weight: 700; cursor: pointer; margin-top: 8px; box-shadow: 0 4px 14px -4px rgba(37,99,235,0.30); transition: background 0.16s, transform 0.16s, box-shadow 0.16s; }
    .signup-btn:hover { background: #1d4ed8; transform: translateY(-1px); box-shadow: 0 12px 26px -8px rgba(37,99,235,0.30); }
    .msg { font-size: 0.85rem; font-weight: 600; margin-top: 14px; min-height: 20px; text-align: center; }
    .msg.error { color: #dc2626; }
    .msg.ok { color: #16a34a; }
    .back-link { margin-top: 18px; text-align: center; font-size: 0.85rem; }
    .back-link a { color: #2563eb; font-weight: 700; text-decoration: none; }
  </style>
</head>
<body>
  <div class="login-page">
    <div class="login-overlay"></div>

    <header class="login-header">
      <div class="login-header-inner">
        <div class="header-left">
          <a class="back-to-portal" href="/" title="Back to Lepra Stack" aria-label="Back to Lepra Stack">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5"></path><path d="M12 19l-7-7 7-7"></path></svg>
          </a>
          <span class="header-divider"></span>
          <div class="brand-mark-group">
            <span class="brand-mark">🦶</span>
            <div>
              <div class="brand-title">LEPRA</div>
              <div class="brand-subtitle" data-i18n="brand_subtitle">Foot Measurement System</div>
            </div>
          </div>
        </div>
        <div class="login-lang">
          <select id="signup-lang-select" onchange="setSignupLang(this.value)">
            <option value="en">English</option>
            <option value="hi">हिन्दी</option>
            <option value="or">ଓଡ଼ିଆ</option>
            <option value="te">తెలుగు</option>
            <option value="mr">मराठी</option>
          </select>
        </div>
      </div>
    </header>

    <main class="login-main">
  <div class="signup-card">
    <h1>Agent Registration</h1>
    <p class="sub">Create your account to start uploading foot images to <strong>LEPRA</strong>.</p>
    <form id="signup-form">
      <div class="form-row">
        <div><label>Full Name *</label><input type="text" name="name" required></div>
        <div><label>Phone</label><input type="tel" name="phone" maxlength="10" inputmode="numeric" pattern="[0-9]{10}" placeholder="10 digits" oninput="this.value=this.value.replace(/\D/g,'').slice(0,10)"></div>
      </div>
      <div class="form-row full">
        <div><label>Email</label><input type="email" name="email"></div>
      </div>
      <div class="form-row">
        <div><label>State</label>
          <select name="state" id="signup-state" onchange="updateCenters()">
            <option value="">Select state</option>
          </select>
        </div>
        <div><label>Center</label>
          <select name="center" id="signup-center">
            <option value="">Select center</option>
          </select>
        </div>
      </div>
      <div class="form-row">
        <div><label>Username *</label><input type="text" name="username" autocapitalize="none" autocorrect="off" spellcheck="false" required></div>
        <div style="position:relative;">
          <label>Password *</label>
          <input type="password" name="password" id="signup-pw" required minlength="4" style="padding-right:42px;">
          <button type="button" class="pw-eye" data-target="signup-pw" tabindex="-1" aria-label="Show password" style="position:absolute;right:8px;top:32px;background:none;border:0;cursor:pointer;padding:6px;font-size:16px;color:#666;">👁</button>
          <div class="caps-warn" data-for="signup-pw" style="display:none;color:#c0392b;font-size:0.8rem;margin-top:4px;">⚠ Caps Lock is on</div>
        </div>
      </div>
      <button class="signup-btn" type="submit">Create Account</button>
      <div class="msg" id="signup-msg"></div>
    </form>
    <div class="back-link"><a href="{{BASE}}/">&larr; Back to Login</a></div>
  </div>
    </main>

    <footer class="site-footer-bar">
      <div class="site-footer-inner">
        <div>&copy; DIMPLE &middot; <span data-i18n="footer_authorised">For authorised health workers only</span></div>
        <div class="footer-partners">
          <span class="footer-partners-label" data-i18n="footer_partnership">In partnership with</span>
          <div class="footer-logos">
            <a href="https://leprasociety.in/" target="_blank" rel="noopener noreferrer"><img src="/samples/lepra-logo.png" alt="LEPRA Society"></a>
            <span class="footer-dot" aria-hidden="true">&middot;</span>
            <img src="/samples/iihmr-logo-footer.png" alt="IIHMR Bangalore">
            <span class="footer-dot" aria-hidden="true">&middot;</span>
            <img src="/samples/kind-care-logo.jpeg" alt="Kind Care">
          </div>
        </div>
      </div>
    </footer>
  </div>
  <script>
    // Shared with the login page's LOGIN_T keys so the language choice made
    // on login (persisted to localStorage) carries over here too.
    const SIGNUP_T = {
      en: { brand_subtitle:"Foot Measurement System", footer_authorised:"For authorised health workers only", footer_partnership:"In partnership with" },
      hi: { brand_subtitle:"पैर माप प्रणाली", footer_authorised:"केवल अधिकृत स्वास्थ्य कार्यकर्ताओं के लिए", footer_partnership:"इनके साथ साझेदारी में" },
      or: { brand_subtitle:"ପାଦ ମାପ ସିଷ୍ଟମ", footer_authorised:"କେବଳ ଅଧିକୃତ ସ୍ୱାସ୍ଥ୍ୟ କର୍ମୀଙ୍କ ପାଇଁ", footer_partnership:"ସହଭାଗିତାରେ" },
      te: { brand_subtitle:"పాద కొలత వ్యవస్థ", footer_authorised:"అధీకృత ఆరోగ్య కార్యకర్తలకు మాత్రమే", footer_partnership:"వీరి భాగస్వామ్యంతో" },
      mr: { brand_subtitle:"पाय मोजमाप प्रणाली", footer_authorised:"केवळ अधिकृत आरोग्य कर्मचाऱ्यांसाठी", footer_partnership:"यांच्या भागीदारीत" }
    };
    function setSignupLang(lang) {
      document.querySelectorAll('[data-i18n]').forEach(el => {
        const k = el.getAttribute('data-i18n');
        if (SIGNUP_T[lang] && SIGNUP_T[lang][k]) el.textContent = SIGNUP_T[lang][k];
      });
      localStorage.setItem('lepra-lang', lang);
      document.getElementById('signup-lang-select').value = lang;
    }
    (function(){ const s = localStorage.getItem('lepra-lang'); if (s && s !== 'en') setSignupLang(s); })();

    const stateSelect = document.getElementById('signup-state');
    const centerSelect = document.getElementById('signup-center');
    let centersMap = {};
    (async function loadSignupOptions() {
      try {
        const r = await fetch('/api/signup-options');
        if (!r.ok) return;
        const data = await r.json();
        centersMap = data.centers || {};
        (data.states || []).forEach(function(s) {
          var o = document.createElement('option');
          o.value = s; o.textContent = s;
          stateSelect.appendChild(o);
        });
      } catch(e) { console.warn('loadSignupOptions error:', e); }
    })();
    function updateCenters() {
      const st = stateSelect.value;
      centerSelect.innerHTML = '<option value="">Select center</option>';
      (centersMap[st] || []).forEach(function(c) {
        const o = document.createElement('option');
        o.value = c; o.textContent = c;
        centerSelect.appendChild(o);
      });
    }
    // Eye toggle + caps-lock warning for the signup password field.
    document.querySelectorAll('.pw-eye').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var inp = document.getElementById(btn.getAttribute('data-target'));
        if (!inp) return;
        var showing = inp.type === 'text';
        inp.type = showing ? 'password' : 'text';
        btn.textContent = showing ? '👁' : '🙈';
        btn.setAttribute('aria-label', showing ? 'Show password' : 'Hide password');
      });
    });
    document.querySelectorAll('.caps-warn').forEach(function(warn) {
      var inp = document.getElementById(warn.getAttribute('data-for'));
      if (!inp) return;
      function check(e) {
        var on = e.getModifierState && e.getModifierState('CapsLock');
        warn.style.display = on ? 'block' : 'none';
      }
      inp.addEventListener('keydown', check);
      inp.addEventListener('keyup', check);
      inp.addEventListener('blur', function() { warn.style.display = 'none'; });
    });

    var _isSigningUp = false;
    document.getElementById('signup-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      if (_isSigningUp) return;
      _isSigningUp = true;
      const msgEl = document.getElementById('signup-msg');
      msgEl.textContent = ''; msgEl.className = 'msg';
      const fd = new FormData(e.target);
      try {
        const r = await fetch('/api/signup', { method: 'POST', body: fd });
        const d = await r.json();
        if (r.ok) {
          msgEl.textContent = d.message || 'Account created! You can now log in.';
          msgEl.className = 'msg ok';
          e.target.reset();
        } else {
          msgEl.textContent = d.detail || 'Signup failed.';
          msgEl.className = 'msg error';
        }
      } catch(e) {
        msgEl.textContent = 'Connection error. Please try again.';
        msgEl.className = 'msg error';
      }
      _isSigningUp = false;
    });
  </script>
</body>
</html>
"""

# ─────────────────────────────────────────────────────────────
# Main application shell HTML
# ─────────────────────────────────────────────────────────────
HTML_APP = """
<!doctype html>
<html lang="en" data-theme="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LEPRA &mdash; Foot Measurement System</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #eef3fb;
      --panel: #ffffff;
      --ink: #0f1d36;
      --muted: #6a7896;
      --line: #d3deef;
      --accent: #2563eb;
      --accent-hover: #1d4ed8;
      --accent-light: rgba(37,99,235,0.08);
      --teal: #2563eb;
      --teal-light: rgba(37,99,235,0.1);
      --warn: #f59e0b;
      --warn-light: #fef3c7;
      --warn-text: #92400e;
      --error: #dc2626;
      --error-light: #fee2e2;
      --success: #16a34a;
      --success-light: #dcfce7;
      --radius: 12px;
      --shadow-sm: 0 1px 2px 0 rgba(30,58,138,0.06), 0 4px 12px -2px rgba(30,58,138,0.08);
      --shadow-md: 0 12px 32px -10px rgba(30,58,138,0.28), 0 4px 12px -4px rgba(15,23,42,0.10);
      --shadow-lg: 0 18px 44px -12px rgba(30,58,138,0.34), 0 8px 18px -6px rgba(15,23,42,0.12);
      --sidebar-w: 260px;
      --sidebar-collapsed-w: 64px;
      --topbar-h: 56px;
    }
    [data-theme="dark"] {
      --bg: #0a1426;
      --panel: #111e36;
      --ink: #e8eefb;
      --muted: #8294b5;
      --line: #233861;
      --accent: #60a5fa;
      --accent-hover: #93c5fd;
      --accent-light: rgba(96,165,250,0.15);
      --warn-light: rgba(245,158,11,0.15);
      --warn-text: #fcd34d;
      --error-light: rgba(220,38,38,0.15);
      --success-light: rgba(22,163,74,0.15);
      --shadow-sm: 0 1px 2px 0 rgba(0,0,0,0.30), 0 4px 14px -2px rgba(0,0,0,0.40);
      --shadow-md: 0 14px 36px -10px rgba(0,0,0,0.55), 0 4px 12px -4px rgba(0,0,0,0.40);
    }
    [data-theme="dark"] input,
    [data-theme="dark"] select,
    [data-theme="dark"] textarea {
      background: #374151 !important;
      color: var(--ink) !important;
      border-color: #4b5563 !important;
    }
    [data-theme="dark"] .meas-table thead th,
    [data-theme="dark"] .patient-summary,
    [data-theme="dark"] pre {
      background: #111827 !important;
    }
    [data-theme="dark"] .upload-cell:hover { background: rgba(37,99,235,0.1); }
    [data-theme="dark"] .upload-cell.has-file { background: rgba(22,163,74,0.1); border-color: var(--success); }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body { overflow-x: hidden; }
    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      color: var(--ink);
      background: var(--bg);
      line-height: 1.5;
      width: 100%;
    }

    /* ── Sidebar ── */
    .sidebar {
      position: fixed;
      top: 0; left: 0; bottom: 0;
      width: var(--sidebar-w);
      background: linear-gradient(180deg, #2563eb 0%, #1e40af 100%);
      color: #fff;
      display: flex;
      flex-direction: column;
      transition: width 0.25s ease;
      z-index: 200;
      overflow: hidden;
    }
    .sidebar-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 18px;
      border-bottom: 1px solid rgba(255,255,255,0.08);
      min-height: 56px;
    }
    .sidebar-logo {
      font-size: 1.4rem;
      font-weight: 700;
      white-space: nowrap;
    }
    .sidebar-logo span { color: rgba(255,255,255,0.7); font-weight: 400; }
    .sidebar-partner-logos {
      display: flex;
      flex-direction: column;
      gap: 6px;
      flex: 1;
      min-width: 0;
      overflow: hidden;
    }
    .sidebar-partner-logos .spl-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .sidebar-partner-logos img {
      height: 32px;
      width: auto;
      object-fit: contain;
      flex-shrink: 0;
    }
    .sidebar-partner-logos .spl-kindcare {
      background: #fff;
      border-radius: 3px;
      padding: 2px 4px;
    }
    .sidebar-partner-logos .spl-iihmr { height: 40px; }
    .sidebar-partner-logos a { display: inline-flex; align-items: center; flex-shrink: 0; }
    .sidebar-toggle {
      background: none;
      border: none;
      color: rgba(255,255,255,0.7);
      cursor: pointer;
      padding: 4px;
      display: flex;
      align-items: center;
    }
    .sidebar-toggle:hover { color: #fff; }
    .sidebar-toggle svg { width: 20px; height: 20px; fill: currentColor; }
    .sidebar-section-label {
      font-size: 0.68rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: rgba(255,255,255,0.35);
      padding: 20px 20px 6px;
      white-space: nowrap;
    }
    .sidebar-item {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 10px 20px;
      color: rgba(255,255,255,0.65);
      text-decoration: none;
      font-size: 0.88rem;
      font-weight: 500;
      transition: background 0.15s, color 0.15s;
      white-space: nowrap;
      cursor: pointer;
      border: none;
      background: none;
      width: 100%;
      text-align: left;
    }
    .sidebar-item:hover { background: rgba(255,255,255,0.07); color: #fff; }
    .sidebar-item.active { background: rgba(255,255,255,0.12); color: #fff; font-weight: 600; }
    .sidebar-icon { display: flex; align-items: center; flex-shrink: 0; }
    .sidebar-icon svg { width: 20px; height: 20px; fill: currentColor; }
    .sidebar-text { white-space: nowrap; }

    body.sidebar-collapsed .sidebar { width: var(--sidebar-collapsed-w); }
    body.sidebar-collapsed .sidebar-text,
    body.sidebar-collapsed .sidebar-section-label { display: none; }
    body.sidebar-collapsed .sidebar-logo,
    body.sidebar-collapsed .sidebar-partner-logos { display: none; }
    body.sidebar-collapsed .sidebar-header { justify-content: center; }

    /* ── Main area ── */
    /* App shell: fixed height column so the top bar stays put and .content is
       the only thing that scrolls. A long intake form then scrolls under the
       header instead of pushing it off screen. */
    .main-area {
      margin-left: var(--sidebar-w);
      transition: margin-left 0.25s ease;
      height: 100vh;
      height: 100dvh;          /* avoids the mobile URL-bar height jump */
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    body.sidebar-collapsed .main-area { margin-left: var(--sidebar-collapsed-w); }

    /* ── Top bar ── */
    .app-topbar {
      height: var(--topbar-h);
      background: var(--panel);
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 24px;
      flex: 0 0 auto;          /* pinned: .content scrolls beneath it */
      z-index: 100;
    }
    .app-topbar .page-title {
      font-size: 1.15rem;
      font-weight: 700;
      color: var(--ink);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      min-width: 0;
    }
    .topbar-back {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 30px;
      height: 30px;
      border-radius: 50%;
      border: 1px solid var(--line);
      color: var(--muted);
      text-decoration: none;
      flex-shrink: 0;
      margin-right: 10px;
      transition: color 0.15s, border-color 0.15s;
    }
    .topbar-back:hover { color: var(--ink); border-color: var(--accent); }
    .topbar-left { display: flex; align-items: center; min-width: 0; flex: 1; overflow: hidden; }
    .profile-area { position: relative; flex-shrink: 0; }
    .profile-btn {
      display: flex;
      align-items: center;
      gap: 10px;
      cursor: pointer;
      padding: 6px 12px;
      border-radius: 8px;
      transition: background 0.15s;
    }
    .profile-btn:hover { background: var(--bg); }
    .avatar {
      width: 34px; height: 34px;
      border-radius: 50%;
      background: #2563eb;
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      font-size: 0.85rem;
    }
    .profile-name {
      font-size: 0.9rem;
      font-weight: 600;
      color: var(--ink);
    }
    .profile-arrow {
      font-size: 0.7rem;
      color: var(--muted);
    }
    .profile-dropdown {
      display: none;
      position: absolute;
      top: 100%;
      right: 0;
      margin-top: 6px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 10px;
      box-shadow: var(--shadow-lg);
      min-width: 220px;
      z-index: 300;
      overflow: hidden;
    }
    .profile-dropdown.open { display: block; }
    .pd-header {
      padding: 16px 18px;
      border-bottom: 1px solid var(--line);
    }
    .pd-name {
      font-weight: 700;
      font-size: 0.95rem;
      color: var(--ink);
    }
    .pd-role {
      font-size: 0.8rem;
      color: var(--muted);
    }
    .pd-item {
      display: block;
      width: 100%;
      padding: 10px 18px;
      border: none;
      background: none;
      font: inherit;
      font-size: 0.88rem;
      color: var(--ink);
      cursor: pointer;
      text-align: left;
      transition: background 0.1s;
    }
    .pd-item:hover { background: var(--bg); }
    .pd-item.danger { color: var(--error); }

    /* ── Content ── */
    .content {
      padding: 24px;
      width: 100%;
      flex: 1 1 auto;
      min-height: 0;           /* lets the flex child shrink so it can scroll */
      overflow-y: auto;
      overscroll-behavior: contain;
    }
    /* Centring moved off .content so the scrollbar sits at the window edge
       rather than against the 1600px box. */
    .section { display: none; max-width: 1600px; margin: 0 auto; }
    .section.active { display: block; }

    /* ── Stats cards ── */
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }
    .stat-card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 20px;
      box-shadow: var(--shadow-sm);
    }
    .stat-card .stat-icon {
      width: 40px; height: 40px;
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      margin-bottom: 12px;
    }
    .stat-card .stat-icon svg { width: 22px; height: 22px; }
    .stat-card .stat-value {
      font-size: 1.8rem;
      font-weight: 700;
      color: var(--ink);
      line-height: 1.2;
    }
    .stat-card .stat-label {
      font-size: 0.82rem;
      color: var(--muted);
      font-weight: 500;
      margin-top: 2px;
    }

    /* ── Reused panel / form styles ── */
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 24px;
      margin-bottom: 20px;
      box-shadow: var(--shadow-sm);
      min-width: 0;
    }
    .section-title {
      font-size: 0.78rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--accent);
      margin-bottom: 12px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .section-title::after {
      content: "";
      flex: 1;
      height: 1px;
      background: var(--line);
    }

    form { display: grid; gap: 0; min-width: 0; }
    .form-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      min-width: 0;
    }
    .form-group {
      display: flex;
      flex-direction: column;
      gap: 4px;
      min-width: 0;
    }
    .form-group .lbl {
      font-size: 0.82rem;
      font-weight: 600;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .form-group .lbl .req { color: var(--error); }
    input[type="text"],
    input[type="number"],
    input[type="date"],
    input[type="tel"],
    input[type="email"],
    input[type="search"],
    select,
    textarea {
      width: 100%;
      min-width: 0;
      padding: 9px 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ink);
      font: inherit;
      font-size: 0.92rem;
      transition: border-color 0.15s;
    }
    input:focus, select:focus, textarea:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-light);
    }
    textarea { resize: vertical; min-height: 60px; }

    /* ── Upload grid ── */
    .upload-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
    }
    .upload-cell {
      border: 2px dashed var(--line);
      border-radius: 8px;
      padding: 14px 12px;
      text-align: center;
      cursor: pointer;
      transition: border-color 0.2s, background 0.2s;
      position: relative;
    }
    .upload-cell:hover { border-color: var(--accent); background: var(--accent-light); }
    .upload-cell.has-file { border-color: var(--success); background: var(--success-light); }
    .upload-cell .view-label {
      font-size: 0.82rem;
      font-weight: 600;
      color: var(--ink);
      margin-bottom: 4px;
    }
    .upload-cell .view-hint {
      font-size: 0.72rem;
      color: var(--muted);
    }
    .upload-cell .file-name {
      font-size: 0.72rem;
      color: var(--success);
      font-weight: 600;
      margin-top: 4px;
      word-break: break-all;
    }
    .upload-cell .preview-img {
      max-width: 100%;
      max-height: 120px;
      border-radius: 6px;
      margin-top: 8px;
      display: none;
      object-fit: cover;
    }
    .upload-cell.has-file .preview-img { display: block; }
    .upload-cell.has-file .view-hint { display: none; }
    /* Per-cell validation badges */
    .validate-badge {
      position: absolute;
      top: 5px;
      left: 6px;
      font-size: 0.72rem;
      font-weight: 700;
      border-radius: 10px;
      padding: 2px 7px;
      z-index: 5;
      pointer-events: none;
    }
    .validate-badge.loading {
      background: #f0c040;
      color: #5a4000;
    }
    .validate-badge.ok {
      background: var(--success);
      color: #fff;
    }
    .validate-badge.fail {
      background: var(--error);
      color: #fff;
    }
    .validate-badge.warn {
      background: #dd6b20;
      color: #fff;
    }
    .card-warn-icon {
      position: absolute;
      bottom: 5px;
      left: 6px;
      font-size: 0.7rem;
      background: #dd6b20;
      color: #fff;
      border-radius: 8px;
      padding: 1px 6px;
      z-index: 5;
      pointer-events: none;
    }
    /* Manual override select */
    .manual-view-select {
      display: none;
      width: 100%;
      margin-top: 6px;
      font-size: 0.8rem;
      border-radius: 6px;
      border: 1px solid var(--accent);
      padding: 3px 4px;
      background: var(--card);
      color: var(--fg);
    }
    .upload-cell input[type="file"] {
      position: absolute;
      inset: 0;
      opacity: 0;
      pointer-events: none;
    }
    /* Camera-vs-gallery choice sheet, shown before either file picker opens */
    .photo-source-overlay {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.5);
      z-index: 2000;
      align-items: flex-end;
      justify-content: center;
    }
    .photo-source-sheet {
      background: var(--panel);
      width: 100%;
      max-width: 420px;
      border-radius: 16px 16px 0 0;
      padding: 20px 16px 28px;
      box-shadow: 0 -8px 32px rgba(0,0,0,0.18);
    }
    .photo-source-title {
      font-weight: 700;
      font-size: 1rem;
      text-align: center;
      margin-bottom: 14px;
      color: var(--ink);
    }
    .photo-source-btn {
      width: 100%;
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 14px 16px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--bg);
      font-family: inherit;
      font-size: 0.95rem;
      font-weight: 600;
      color: var(--ink);
      cursor: pointer;
      margin-bottom: 10px;
      transition: border-color 0.15s, background 0.15s;
    }
    .photo-source-btn:hover { border-color: var(--accent); background: var(--accent-light); }
    .photo-source-btn svg { color: var(--accent); flex-shrink: 0; }
    .photo-source-cancel {
      width: 100%;
      padding: 14px;
      border: none;
      background: none;
      font-family: inherit;
      color: var(--muted);
      font-size: 0.9rem;
      font-weight: 600;
      cursor: pointer;
      text-align: center;
    }
    .sample-help-btn {
      position: absolute;
      top: 6px;
      right: 6px;
      width: 22px;
      height: 22px;
      border-radius: 50%;
      border: 1.5px solid var(--muted);
      background: var(--card);
      color: var(--muted);
      font-size: 0.72rem;
      font-weight: 700;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      z-index: 2;
      transition: border-color 0.2s, color 0.2s, background 0.2s;
      line-height: 1;
    }
    .sample-help-btn:hover {
      border-color: var(--accent);
      color: var(--accent);
      background: var(--accent-light);
    }
    .camera-badge {
      position: absolute;
      bottom: 6px;
      right: 6px;
      width: 26px;
      height: 26px;
      border-radius: 50%;
      background: var(--accent);
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 2;
      pointer-events: none;
      box-shadow: 0 2px 6px -1px rgba(0,0,0,0.25);
    }
    .upload-cell.has-file .camera-badge { display: none; }
    .sample-modal-overlay {
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.6);
      z-index: 9999;
      display: flex;
      align-items: center;
      justify-content: center;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.2s;
    }
    .sample-modal-overlay.visible {
      opacity: 1;
      pointer-events: auto;
    }
    .sample-modal {
      background: var(--card);
      border-radius: 12px;
      padding: 20px;
      max-width: 520px;
      width: 90%;
      max-height: 85vh;
      overflow-y: auto;
      box-shadow: 0 20px 60px rgba(0,0,0,0.3);
      position: relative;
    }
    .sample-modal-close {
      position: absolute;
      top: 10px;
      right: 12px;
      background: none;
      border: none;
      font-size: 1.3rem;
      color: var(--muted);
      cursor: pointer;
      line-height: 1;
    }
    .sample-modal-close:hover { color: var(--ink); }
    .sample-modal h3 {
      font-size: 0.95rem;
      font-weight: 700;
      color: var(--ink);
      margin-bottom: 12px;
    }
    .sample-modal img {
      width: 100%;
      border-radius: 8px;
      border: 1px solid var(--line);
    }
    .sample-modal .sample-note {
      font-size: 0.78rem;
      color: var(--muted);
      margin-top: 10px;
      text-align: center;
    }
    .foot-side-label {
      font-size: 0.78rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
      margin-bottom: 8px;
      padding-bottom: 4px;
      border-bottom: 2px solid var(--line);
    }

    /* ── Toggles & buttons ── */
    .toggles {
      display: flex;
      flex-wrap: wrap;
      gap: 20px;
      padding-top: 4px;
    }
    .toggle {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 0.88rem;
      color: var(--ink);
      cursor: pointer;
    }
    .toggle input[type="checkbox"] {
      width: 16px; height: 16px;
      accent-color: var(--accent);
    }
    .actions {
      display: flex;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
    }
    .btn-primary {
      padding: 11px 28px;
      border: 0;
      border-radius: 6px;
      background: var(--accent);
      color: #fff;
      font: inherit;
      font-weight: 600;
      font-size: 0.95rem;
      cursor: pointer;
      transition: background 0.15s;
    }
    .btn-primary:hover { background: var(--accent-hover); }
    .btn-primary:disabled { opacity: 0.5; cursor: wait; }
    .status {
      min-height: 20px;
      font-size: 0.88rem;
      color: var(--muted);
    }
    .status.error { color: var(--error); font-weight: 600; }

    /* ── Guidelines ── */
    .guidelines {
      background: var(--accent-light);
      border: 1px solid rgba(37,99,235,0.2);
      border-radius: 8px;
      padding: 14px 18px;
      margin-bottom: 16px;
    }
    .guidelines summary {
      cursor: pointer;
      font-weight: 600;
      font-size: 0.88rem;
      color: var(--accent);
    }
    .guidelines ul {
      margin: 10px 0 0 16px;
      font-size: 0.84rem;
      line-height: 1.7;
      color: var(--ink);
    }
    .guidelines li { margin-bottom: 2px; }

    /* ── Progress bar ── */
    .progress-wrap {
      display: none;
      flex-direction: column;
      gap: 6px;
      margin-top: 8px;
    }
    .progress-wrap.visible { display: flex; }
    .progress-bar {
      height: 6px;
      background: var(--line);
      border-radius: 4px;
      overflow: hidden;
    }
    .progress-fill {
      height: 100%;
      width: 0%;
      background: linear-gradient(90deg, var(--accent), #0ea5e9);
      border-radius: 4px;
      transition: width 0.35s ease;
    }
    .progress-label {
      font-size: 0.82rem;
      color: var(--muted);
    }

    /* ── Inline loading spinner (reused wherever a section is fetching data) ── */
    .spinner {
      display: inline-block;
      width: 16px;
      height: 16px;
      border: 2px solid var(--line);
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: spin 0.7s linear infinite;
      vertical-align: -3px;
      margin-right: 8px;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }

    /* ── Results ── */
    .result {
      display: none;
      gap: 20px;
    }
    .result.visible { display: grid; }
    .result-header {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }
    .badge {
      display: inline-block;
      padding: 3px 10px;
      border-radius: 12px;
      font-size: 0.76rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .badge-trusted { background: var(--success-light); color: var(--success); }
    .badge-degraded { background: var(--warn-light); color: var(--warn-text); }
    .badge-error { background: var(--error-light); color: var(--error); }
    .meta-links {
      display: flex;
      gap: 12px;
      font-size: 0.84rem;
    }
    .meta-links a {
      color: var(--accent);
      text-decoration: none;
    }
    .meta-links a:hover { text-decoration: underline; }

    .patient-summary {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 8px 16px;
      padding: 14px 16px;
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: 8px;
      font-size: 0.84rem;
    }
    .patient-summary .ps-item { display: flex; gap: 6px; }
    .patient-summary .ps-label { font-weight: 600; color: var(--muted); white-space: nowrap; }
    .patient-summary .ps-value { color: var(--ink); }

    .meas-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.88rem;
    }
    .meas-table th, .meas-table td {
      padding: 10px 14px;
      border-bottom: 1px solid var(--line);
      text-align: left;
    }
    .meas-table thead th {
      background: #f8fafc;
      font-weight: 700;
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--muted);
    }
    .meas-table td.num {
      text-align: right;
      font-variant-numeric: tabular-nums;
      font-weight: 500;
    }
    .meas-table .prov { color: var(--muted); font-style: italic; }
    .meas-table tbody tr:hover { background: #f8fafc; }
    [data-theme="dark"] .meas-table tbody tr:hover { background: #111827; }

    .warnings-box {
      background: var(--warn-light);
      border: 1px solid #fcd34d;
      border-radius: 8px;
      padding: 12px 16px;
      font-size: 0.84rem;
    }
    .warnings-box .wb-title { font-weight: 700; color: var(--warn-text); margin-bottom: 6px; }
    .warnings-box ul { margin: 0 0 0 16px; color: var(--warn-text); }
    .warnings-box li { margin-bottom: 2px; }

    details { margin-top: 8px; }
    details summary { cursor: pointer; color: var(--muted); font-size: 0.84rem; }
    pre {
      margin: 8px 0 0;
      padding: 14px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #f8fafc;
      font-size: 0.82rem;
    }
    .sep { height: 1px; background: var(--line); margin: 20px 0; }

    /* ── Visualization gallery ── */
    .viz-section { margin-top: 16px; }
    .viz-section h4 {
      font-size: 0.85rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--muted);
      margin-bottom: 10px;
    }
    .viz-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
    }
    @media (max-width: 900px) { .viz-grid { grid-template-columns: repeat(2, 1fr); } }
    @media (max-width: 540px) { .viz-grid { grid-template-columns: 1fr; } }
    .viz-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: var(--panel);
    }
    .viz-card img {
      width: 100%;
      display: block;
      cursor: pointer;
      transition: transform 0.15s;
    }
    .viz-card img:hover { transform: scale(1.02); }
    .viz-card .viz-label {
      padding: 6px 10px;
      font-size: 0.76rem;
      font-weight: 600;
      color: var(--muted);
      text-align: center;
      border-top: 1px solid var(--line);
    }
    .btn-secondary {
      padding: 10px 22px;
      border: 1.5px solid var(--accent);
      border-radius: 6px;
      background: transparent;
      color: var(--accent);
      font-family: inherit;
      font-weight: 600;
      font-size: 0.9rem;
      cursor: pointer;
      transition: background 0.15s, color 0.15s;
    }
    .btn-secondary:hover { background: var(--accent); color: #fff; }
    .result-actions {
      display: flex;
      gap: 12px;
      margin-top: 16px;
      flex-wrap: wrap;
    }

    /* ── History table ── */
    .history-empty {
      text-align: center;
      padding: 48px 20px;
      color: var(--muted);
      font-size: 0.95rem;
    }

    /* ── Settings sections ── */
    .settings-card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 24px;
      margin-bottom: 16px;
      box-shadow: var(--shadow-sm);
    }
    .settings-card h3 {
      font-size: 1rem;
      font-weight: 700;
      margin-bottom: 6px;
      color: var(--ink);
    }
    .settings-card p {
      font-size: 0.88rem;
      color: var(--muted);
      margin-bottom: 14px;
    }
    .theme-options {
      display: flex;
      gap: 16px;
    }
    .theme-card {
      flex: 1;
      padding: 20px;
      border: 2px solid var(--line);
      border-radius: 10px;
      cursor: pointer;
      text-align: center;
      transition: border-color 0.15s, background 0.15s;
    }
    .theme-card:hover { border-color: var(--accent); }
    .theme-card.active { border-color: var(--accent); background: var(--accent-light); }
    .theme-card .theme-preview {
      width: 48px; height: 32px;
      border-radius: 6px;
      margin: 0 auto 8px;
      border: 1px solid var(--line);
    }
    .theme-card .theme-name { font-weight: 600; font-size: 0.9rem; color: var(--ink); }

    /* ── Responsive ── */
    @media (max-width: 1023px) {
      body:not(.sidebar-expanded) .sidebar { width: var(--sidebar-collapsed-w); }
      body:not(.sidebar-expanded) .sidebar .sidebar-text,
      body:not(.sidebar-expanded) .sidebar .sidebar-section-label { display: none; }
      body:not(.sidebar-expanded) .sidebar .sidebar-logo,
      body:not(.sidebar-expanded) .sidebar .sidebar-partner-logos { display: none; }
      body:not(.sidebar-expanded) .sidebar .sidebar-header { justify-content: center; }
      body:not(.sidebar-expanded) .main-area { margin-left: var(--sidebar-collapsed-w); }
    }
    /* Mobile hamburger button (hidden on desktop) */
    .mob-menu-btn { display: none; }

    /* Sidebar backdrop overlay */
    .sidebar-backdrop {
      display: none;
      position: fixed; inset: 0;
      background: rgba(0,0,0,0.45);
      z-index: 199;
    }
    body.sidebar-expanded .sidebar-backdrop { display: block; }

    @media (max-width: 767px) {
      .sidebar {
        transform: translateX(-100%);
        width: var(--sidebar-w) !important;
      }
      body.sidebar-expanded .sidebar { transform: translateX(0); }
      body.sidebar-expanded { overflow: hidden; }
      .main-area { margin-left: 0 !important; }
      .stats-grid { grid-template-columns: 1fr 1fr; }
      .content { padding: 16px; }
      .upload-grid { grid-template-columns: 1fr !important; }
      .form-grid { grid-template-columns: 1fr !important; }
      .meas-table { display: block; overflow-x: auto; }
      .btn-primary, .btn-secondary { min-height: 44px; font-size: 0.95rem; }
      .upload-cell { min-height: 120px; }
      .mob-menu-btn {
        display: flex; align-items: center; justify-content: center;
        background: none; border: none; cursor: pointer;
        color: var(--ink); padding: 8px; margin-right: 8px;
        border-radius: 6px; flex-shrink: 0;
      }
      .mob-menu-btn:hover { background: var(--hover); }
      .app-topbar { padding: 0 12px; }
      .app-topbar .page-title { font-size: 1rem; }
      .topbar-back { width: 26px; height: 26px; margin-right: 6px; }
      .profile-btn { padding: 4px 6px; gap: 6px; }
    }
    @media (max-width: 480px) {
      .stats-grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 420px) {
      .profile-name, .profile-arrow { display: none; }
    }
    /* Small inline-styled row-action buttons (History "Edit", Agent
       Revoke/Approve/Reset PW) render well under the 44px touch target on
       mobile since their own inline padding/font-size beats normal CSS —
       force a real touch-friendly size with !important on small screens. */
    @media (max-width: 767px) {
      .tbl-action-btn {
        padding: 10px 14px !important;
        font-size: 0.85rem !important;
        min-height: 44px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }
    }
    /* About Us page grids — were inline `style="display:grid"`, which no
       media query could ever override (inline styles beat classed rules).
       Moved the column count to these classes so mobile can collapse them. */
    .about-grid-2, .about-grid-3, .about-grid-4, .about-grid-21 { display: grid; }
    .about-grid-2 { grid-template-columns: 1fr 1fr; }
    .about-grid-3 { grid-template-columns: repeat(3,1fr); }
    .about-grid-4 { grid-template-columns: repeat(4,1fr); }
    .about-grid-21 { grid-template-columns: 2fr 1fr; }
    @media (max-width: 767px) {
      .about-grid-2, .about-grid-3, .about-grid-4, .about-grid-21 { grid-template-columns: 1fr; }
    }
    .charts-grid { display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-top:20px; }
    @media (max-width: 700px) { .charts-grid { grid-template-columns: 1fr; } }
    .chart-panel { background:var(--panel); border-radius:12px; padding:20px; }
    .chart-panel canvas { max-height:220px; }
  </style>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4/dist/chart.umd.min.js"></script>
</head>
<body>

  <!-- ─── Sidebar ─── -->
  <nav class="sidebar" id="sidebar">
    <div class="sidebar-header">
      <div class="sidebar-partner-logos">
        <div class="spl-row">
          <a href="https://leprasociety.in/" target="_blank" rel="noopener noreferrer" title="LEPRA Society">
            <img src="/samples/lepra-logo.png" onerror="this.style.display='none'" alt="LEPRA Society">
          </a>
          <img src="/samples/kind-care-logo.jpeg" onerror="this.style.display='none'" alt="Kind Care" class="spl-kindcare">
        </div>
        <div class="spl-row">
          <img src="/samples/iihmr-logo-footer.png" onerror="this.style.display='none'" alt="IIHMR" class="spl-iihmr" style="filter:brightness(0) invert(1);">
        </div>
      </div>
      <button class="sidebar-toggle" id="sidebar-toggle" title="Toggle sidebar">
        <svg viewBox="0 0 24 24"><path d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z"/></svg>
      </button>
    </div>
    <div class="sidebar-section-label" data-i18n="nav_overview">OVERVIEW</div>
    <a class="sidebar-item active" data-section="prediction" href="#prediction">
      <span class="sidebar-icon"><svg viewBox="0 0 24 24"><path d="M19.8 18.4L14 10.67V6.5l1.35-1.69c.26-.33.03-.81-.39-.81H9.04c-.42 0-.65.48-.39.81L10 6.5v4.17L4.2 18.4c-.49.66-.02 1.6.8 1.6h14c.82 0 1.29-.94.8-1.6z"/></svg></span>
      <span class="sidebar-text" data-i18n="nav_prediction">Measurement Estimation</span>
    </a>
    <a class="sidebar-item" data-section="dashboard" href="#dashboard">
      <span class="sidebar-icon"><svg viewBox="0 0 24 24"><path d="M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z"/></svg></span>
      <span class="sidebar-text" data-i18n="nav_dashboard">Dashboard</span>
    </a>
    <a class="sidebar-item" data-section="history" href="#history">
      <span class="sidebar-icon"><svg viewBox="0 0 24 24"><path d="M13 3a9 9 0 00-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42A8.954 8.954 0 0013 21a9 9 0 000-18zm-1 5v5l4.28 2.54.72-1.21-3.5-2.08V8H12z"/></svg></span>
      <span class="sidebar-text" data-i18n="nav_history">Patient History</span>
    </a>
    <a class="sidebar-item admin-only" data-section="agents" href="#agents">
      <span class="sidebar-icon"><svg viewBox="0 0 24 24"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg></span>
      <span class="sidebar-text" data-i18n="nav_agents">Agent Management</span>
    </a>
    <div class="sidebar-section-label" data-i18n="nav_settings">SETTINGS</div>
    <a class="sidebar-item" data-section="language" href="#language">
      <span class="sidebar-icon"><svg viewBox="0 0 24 24"><path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zm6.93 6h-2.95a15.65 15.65 0 00-1.38-3.56A8.03 8.03 0 0118.92 8zM12 4.04c.83 1.2 1.48 2.53 1.91 3.96h-3.82c.43-1.43 1.08-2.76 1.91-3.96zM4.26 14C4.1 13.36 4 12.69 4 12s.1-1.36.26-2h3.38c-.08.66-.14 1.32-.14 2s.06 1.34.14 2H4.26zM5.08 16h2.95c.32 1.25.78 2.45 1.38 3.56A7.987 7.987 0 015.08 16zm2.95-8H5.08a7.987 7.987 0 014.33-3.56A15.65 15.65 0 008.03 8zM12 19.96c-.83-1.2-1.48-2.53-1.91-3.96h3.82c-.43 1.43-1.08 2.76-1.91 3.96zM14.34 14H9.66c-.09-.66-.16-1.32-.16-2s.07-1.35.16-2h4.68c.09.65.16 1.32.16 2s-.07 1.34-.16 2zm.25 5.56c.6-1.11 1.06-2.31 1.38-3.56h2.95a8.03 8.03 0 01-4.33 3.56zM16.36 14c.08-.66.14-1.32.14-2s-.06-1.34-.14-2h3.38c.16.64.26 1.31.26 2s-.1 1.36-.26 2h-3.38z"/></svg></span>
      <span class="sidebar-text" data-i18n="nav_language">Language</span>
    </a>
    <a class="sidebar-item" data-section="about" href="#about">
      <span class="sidebar-icon"><svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg></span>
      <span class="sidebar-text" data-i18n="nav_about">About Us</span>
    </a>
    <a class="sidebar-item" data-section="help" href="#help">
      <span class="sidebar-icon"><svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 17h-2v-2h2v2zm2.07-7.75l-.9.92C13.45 12.9 13 13.5 13 15h-2v-.5c0-1.1.45-2.1 1.17-2.83l1.24-1.26c.37-.36.59-.86.59-1.41 0-1.1-.9-2-2-2s-2 .9-2 2H8c0-2.21 1.79-4 4-4s4 1.79 4 4c0 .88-.36 1.68-.93 2.25z"/></svg></span>
      <span class="sidebar-text" data-i18n="nav_help">Help & Support</span>
    </a>
    <a class="sidebar-item" data-section="theme" href="#theme">
      <span class="sidebar-icon"><svg viewBox="0 0 24 24"><path d="M12 3c-4.97 0-9 4.03-9 9s4.03 9 9 9c.83 0 1.5-.67 1.5-1.5 0-.39-.15-.74-.39-1.01-.23-.26-.38-.61-.38-1 0-.83.67-1.5 1.5-1.5H16c2.76 0 5-2.24 5-5 0-4.42-4.03-8-9-8zm-5.5 9c-.83 0-1.5-.67-1.5-1.5S5.67 9 6.5 9 8 9.67 8 10.5 7.33 12 6.5 12zm3-4C8.67 8 8 7.33 8 6.5S8.67 5 9.5 5s1.5.67 1.5 1.5S10.33 8 9.5 8zm5 0c-.83 0-1.5-.67-1.5-1.5S13.67 5 14.5 5s1.5.67 1.5 1.5S15.33 8 14.5 8zm3 4c-.83 0-1.5-.67-1.5-1.5S16.67 9 17.5 9s1.5.67 1.5 1.5-.67 1.5-1.5 1.5z"/></svg></span>
      <span class="sidebar-text" data-i18n="nav_theme">Theme</span>
    </a>
  </nav>

  <!-- ─── Main area ─── -->
  <div class="main-area">
    <!-- Top bar -->
    <header class="app-topbar">
      <div class="topbar-left">
        <button class="mob-menu-btn" id="mob-menu-btn" aria-label="Open menu">
          <svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><path d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z"/></svg>
        </button>
        <a class="topbar-back" href="/" title="Lepra Stack Home" aria-label="Lepra Stack Home">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline></svg>
        </a>
        <h2 class="page-title" id="page-title">Dashboard</h2>
      </div>
      <div class="profile-area">
        <div class="profile-btn" id="profile-btn">
          <div class="avatar" id="profile-avatar">A</div>
          <span class="profile-name" id="profile-name-display">Admin</span>
          <span class="profile-arrow">&#9662;</span>
        </div>
        <div class="profile-dropdown" id="profile-dropdown">
          <div class="pd-header">
            <div class="pd-name" id="pd-name-display">Administrator</div>
            <div class="pd-role" id="pd-role-display">System Admin</div>
          </div>
          <button class="pd-item pd-item-logout danger" id="logout-btn" data-i18n="logout">Logout</button>
        </div>
      </div>
    </header>

    <div class="content">

      <!-- ═══ DASHBOARD ═══ -->
      <div id="sec-dashboard" class="section">
        <div class="stats-grid" id="stats-grid">
          <div class="stat-card">
            <div class="stat-icon" style="background:var(--accent-light);">
              <svg viewBox="0 0 24 24" fill="var(--accent)"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-5 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z"/></svg>
            </div>
            <div class="stat-value" id="stat-total">--</div>
            <div class="stat-label" data-i18n="stat_total_predictions">Total Predictions</div>
          </div>
          <div class="stat-card">
            <div class="stat-icon" style="background:var(--success-light);">
              <svg viewBox="0 0 24 24" fill="var(--success)"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/></svg>
            </div>
            <div class="stat-value" id="stat-success">--</div>
            <div class="stat-label" data-i18n="stat_successful_runs">Completed Estimations</div>
          </div>
          <div class="stat-card">
            <div class="stat-icon" style="background:var(--warn-light);">
              <svg viewBox="0 0 24 24" fill="var(--warn)"><path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67V7z"/></svg>
            </div>
            <div class="stat-value" id="stat-recent">--</div>
            <div class="stat-label" data-i18n="stat_last_run">Last Run</div>
          </div>
          <div class="stat-card">
            <div class="stat-icon" style="background:#ede9fe;">
              <svg viewBox="0 0 24 24" fill="#7c3aed"><path d="M15 1H9v2h6V1zm-4 13h2V8h-2v6zm8.03-6.61l1.42-1.42c-.43-.51-.9-.99-1.41-1.41l-1.42 1.42A8.962 8.962 0 0012 4c-4.97 0-9 4.03-9 9s4.03 9 9 9 9-4.03 9-9c0-2.12-.74-4.07-1.97-5.61zM12 20c-3.87 0-7-3.13-7-7s3.13-7 7-7 7 3.13 7 7-3.13 7-7 7z"/></svg>
            </div>
            <div class="stat-value" id="stat-avgtime">--</div>
            <div class="stat-label" data-i18n="stat_avg_time">Avg. Inference Time</div>
          </div>
        </div>
        <div class="panel">
          <div class="section-title" data-i18n="recent_predictions">Recent Estimations</div>
          <div id="recent-runs"></div>
        </div>
        <div id="charts-grid" style="display:none;">
          <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:16px;">
            <span style="font-size:0.88rem;color:var(--muted);">From</span>
            <input type="date" id="dash-date-from" onchange="filterDashboard()" style="padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink);font-size:0.88rem;">
            <span style="font-size:0.88rem;color:var(--muted);">to</span>
            <input type="date" id="dash-date-to" onchange="filterDashboard()" style="padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink);font-size:0.88rem;">
            <button onclick="clearDashboardDates()" style="padding:6px 12px;border:1px solid var(--line);border-radius:6px;background:none;color:var(--muted);cursor:pointer;font-size:0.82rem;">Clear</button>
          </div>
          <div class="charts-grid">
            <div class="chart-panel">
              <div class="section-title" style="margin-bottom:12px;">Patients per Month</div>
              <canvas id="chart-by-month"></canvas>
            </div>
            <div class="chart-panel">
              <div class="section-title" style="margin-bottom:12px;">Patients by Centre</div>
              <canvas id="chart-by-center"></canvas>
            </div>
            <div class="chart-panel">
              <div class="section-title" style="margin-bottom:12px;">Gender Distribution</div>
              <canvas id="chart-by-gender"></canvas>
            </div>
          </div>
        </div>
        <div id="drilldown-grid" style="display:none;margin-top:20px;">
          <div class="panel" style="margin-bottom:16px;">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">
              <div class="section-title" style="margin-bottom:0;">Regional Coverage</div>
              <button onclick="openDrilldownSummary()" style="padding:8px 14px;border:1px solid var(--line);border-radius:6px;background:var(--accent);color:#fff;cursor:pointer;font-size:0.85rem;font-weight:600;">View Summary</button>
            </div>
            <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:14px 0;">
              <span style="font-size:0.88rem;color:var(--muted);">From</span>
              <input type="date" id="dd-date-from" onchange="reloadDrilldown()" style="padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink);font-size:0.88rem;">
              <span style="font-size:0.88rem;color:var(--muted);">to</span>
              <input type="date" id="dd-date-to" onchange="reloadDrilldown()" style="padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink);font-size:0.88rem;">
              <select id="dd-state-filter" onchange="_onStateFilterChange()" style="padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink);font-size:0.88rem;">
                <option value="">All States</option>
              </select>
              <select id="dd-district-filter" onchange="_onDistrictFilterChange()" disabled style="padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink);font-size:0.88rem;">
                <option value="">Select a state first</option>
              </select>
              <select id="dd-user-filter" onchange="_renderDrilldownLevel()" disabled style="padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink);font-size:0.88rem;">
                <option value="">Select a state first</option>
              </select>
              <button onclick="clearDrilldownDates()" style="padding:6px 12px;border:1px solid var(--line);border-radius:6px;background:none;color:var(--muted);cursor:pointer;font-size:0.82rem;">Clear</button>
            </div>
            <div id="dd-breadcrumb" style="font-size:0.85rem;color:var(--muted);margin-bottom:10px;">
              <span onclick="_drilldownGoTo(0)" style="cursor:pointer;text-decoration:underline;">All States</span>
            </div>
            <canvas id="chart-drilldown" height="90"></canvas>
          </div>
        </div>
      </div>

      <div id="drilldown-summary-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:1000;align-items:center;justify-content:center;overflow-y:auto;">
        <div style="background:var(--panel);border-radius:12px;padding:28px;width:480px;max-width:94vw;box-shadow:0 8px 32px rgba(0,0,0,0.18);margin:40px auto;">
          <div style="font-weight:700;font-size:1.1rem;margin-bottom:18px;">Cumulative Summary</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px 18px;margin-bottom:18px;">
            <div>
              <div style="font-size:0.78rem;color:var(--muted);">Total Patients</div>
              <div style="font-size:1.4rem;font-weight:700;" id="dds-total-patients">--</div>
            </div>
            <div>
              <div style="font-size:0.78rem;color:var(--muted);">Total Measurements</div>
              <div style="font-size:1.4rem;font-weight:700;" id="dds-total-measurements">--</div>
            </div>
            <div>
              <div style="font-size:0.78rem;color:var(--muted);">Completion Rate</div>
              <div style="font-size:1.4rem;font-weight:700;" id="dds-completion-rate">--</div>
            </div>
            <div>
              <div style="font-size:0.78rem;color:var(--muted);">Period</div>
              <div style="font-size:0.95rem;font-weight:600;" id="dds-period">All time</div>
            </div>
          </div>
          <button onclick="document.getElementById('drilldown-summary-modal').style.display='none'" style="width:100%;padding:10px;border:1px solid var(--line);border-radius:6px;cursor:pointer;background:var(--panel);color:var(--ink);">Close</button>
        </div>
      </div>

      <!-- ═══ MEASUREMENT ESTIMATION ═══ -->
      <div id="sec-prediction" class="section active">
        <div style="margin-bottom:16px;display:flex;gap:12px;align-items:center;">
          <button type="button" class="btn-secondary" id="new-patient-btn" onclick="resetPredictionForm()" style="display:inline-flex;align-items:center;gap:6px;">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>
            <span data-i18n="btn_new_patient">New Patient</span>
          </button>
        </div>
        <form id="run-form">
          <input type="hidden" name="allow_borrowed_scale" value="true">
          <input type="hidden" name="lenient_mode" value="true">
          <div class="panel">
            <div class="section-title" data-i18n="patient_information">Patient Information</div>
            <div class="form-grid" style="margin-bottom:14px;">
              <div class="form-group">
                <span class="lbl"><span data-i18n="lbl_patient_id">Patient ID</span> <span class="req">*</span></span>
                <input type="text" name="patient_id" value="PAT-001" required style="text-transform:uppercase;" oninput="this.value=this.value.toUpperCase()">
              </div>
              <div class="form-group">
                <span class="lbl"><span data-i18n="lbl_patient_name">Patient Name</span> <span class="req">*</span></span>
                <input type="text" name="patient_name" data-i18n-ph="ph_full_name" placeholder="Full name" required>
              </div>
              <div class="form-group">
                <span class="lbl"><span data-i18n="lbl_age">Age</span> <span class="req">*</span></span>
                <input type="number" name="age" min="1" max="120" data-i18n-ph="ph_years" placeholder="Years" required>
              </div>
              <div class="form-group">
                <span class="lbl"><span data-i18n="lbl_gender">Gender</span> <span class="req">*</span></span>
                <select name="gender" required>
                  <option value="" data-i18n="opt_select">Select</option>
                  <option value="male" data-i18n="opt_male">Male</option>
                  <option value="female" data-i18n="opt_female">Female</option>
                  <option value="other" data-i18n="opt_other">Other</option>
                </select>
              </div>
            </div>
            <div class="form-grid">
              <div class="form-group">
                <span class="lbl" data-i18n="lbl_abha_id">ABHA ID</span>
                <input type="text" name="abha_id" placeholder="e.g. 12-3456-7890-1234">
              </div>
              <div class="form-group">
                <span class="lbl" data-i18n="lbl_aadhar_id">Aadhar Number</span>
                <input type="text" name="aadhar_id" maxlength="12" inputmode="numeric" pattern="[0-9]{12}" data-i18n-ph="ph_aadhar" placeholder="12 digits" oninput="this.value=this.value.replace(/\D/g,'').slice(0,12)">
              </div>
              <div class="form-group">
                <span class="lbl" data-i18n="lbl_diabetes">Diabetes</span>
                <select name="diabetes">
                  <option value="no" data-i18n="opt_no">No</option>
                  <option value="yes" data-i18n="opt_yes">Yes</option>
                </select>
              </div>
              <div class="form-group">
                <span class="lbl" data-i18n="lbl_amputated_toes">Amputated Toes</span>
                <select name="amputated_toes">
                  <option value="no" data-i18n="opt_no">No</option>
                  <option value="yes" data-i18n="opt_yes">Yes</option>
                </select>
              </div>
              <div class="form-group">
                <span class="lbl" data-i18n="lbl_disease_type">Disease Type</span>
                <select name="disease_type" id="disease-type-select">
                  <option value="leprosy" data-i18n="opt_leprosy" selected>Leprosy</option>
                  <option value="lf" data-i18n="opt_lf">Lymphatic Filariasis (LF)</option>
                </select>
              </div>
              <div class="form-group">
                <span class="lbl" data-i18n="lbl_who_grade">WHO Disability Grade</span>
                <select name="who_grade" id="who-grade-select">
                  <option value="" data-i18n="opt_select">Select</option>
                  <option value="none" data-i18n="opt_grade_none">None</option>
                  <option value="grade_1" data-i18n="opt_grade_1">Grade 1</option>
                  <option value="grade_2" data-i18n="opt_grade_2">Grade 2</option>
                </select>
              </div>
              <div class="form-group">
                <span class="lbl" data-i18n="lbl_exam_date">Date of Examination</span>
                <input type="date" name="exam_date">
              </div>
              <div class="form-group">
                <span class="lbl" data-i18n="lbl_state">State</span>
                <select name="state" id="state-select"><option value="">-- Select State --</option></select>
              </div>
              <div class="form-group">
                <span class="lbl" data-i18n="lbl_district">District</span>
                <select name="district" id="district-select"><option value="">-- Select District --</option></select>
              </div>
              <div class="form-group">
                <span class="lbl" data-i18n="lbl_village">Village</span>
                <input type="text" name="village" data-i18n-ph="ph_village" placeholder="Village name">
              </div>
              <div class="form-group">
                <span class="lbl" data-i18n="lbl_capture_center">Capture Center</span>
                <select name="capture_center" id="center-select"><option value="">-- Select Center --</option></select>
              </div>
              <div class="form-group">
                <span class="lbl" data-i18n="lbl_referring_doctor">Referring Doctor</span>
                <input type="text" name="referring_doctor" placeholder="Dr.">
              </div>
              <div class="form-group">
                <span class="lbl" data-i18n="lbl_phone">Phone Number</span>
                <input type="tel" name="phone" maxlength="10" inputmode="numeric" pattern="[0-9]{10}" data-i18n-ph="ph_phone" placeholder="10 digits (India)" oninput="this.value=this.value.replace(/\D/g,'').slice(0,10)">
              </div>
              <div class="form-group">
                <span class="lbl" data-i18n="lbl_captured_by">Captured By</span>
                <select name="captured_by" id="captured-by-select">
                  <option value="">-- Select --</option>
                  <option value="__other__" data-i18n="opt_other_staff">Other (not in list)</option>
                </select>
                <input type="text" name="captured_by_other" id="captured-by-other" placeholder="Enter name" style="display:none;margin-top:6px;">
              </div>
            </div>
            <div class="form-group" style="margin-top:14px;">
              <span class="lbl" data-i18n="lbl_clinical_notes">Clinical Notes</span>
              <textarea name="clinical_notes" rows="2" data-i18n-ph="ph_clinical_notes" placeholder="Any relevant history, deformities, symptoms..."></textarea>
            </div>
            <div class="form-group" style="margin-top:14px;">
              <span class="lbl" data-i18n="lbl_reference_type">Reference Object Used</span>
              <select name="reference_type">
                <option value="card" data-i18n="ref_card">Standard Debit/Credit Card</option>
                <option value="coin_5rs" data-i18n="ref_coin_5">5 Rs Coin</option>
                <option value="coin_10rs" data-i18n="ref_coin_10">10 Rs Coin</option>
                <option value="aruco" data-i18n="ref_aruco">ArUco Marker Card</option>
              </select>
            </div>
          </div>

          <div class="panel">
            <div class="section-title" data-i18n="foot_images">Foot Images</div>
            <details class="guidelines" open>
              <summary data-i18n="image_guidelines">Image Capture Guidelines</summary>
              <ul>
                <li><b data-i18n="guide_ref_card_b">Reference card:</b> <span data-i18n="guide_ref_card">Place a standard credit/debit card flat on the same surface as the foot — never hold it in hand.</span></li>
                <li><b data-i18n="guide_camera_b">Camera angle:</b> <span data-i18n="guide_camera">Hold the camera perpendicular — directly above for plantar, straight-on for dorsal and medial.</span></li>
                <li><b data-i18n="guide_framing_b">Framing:</b> <span data-i18n="guide_framing">Only the foot and card should be visible. No face, hands, or other body parts in the frame.</span></li>
                <li><b data-i18n="guide_background_b">Background:</b> <span data-i18n="guide_background">Plain, light-coloured surface (white / light grey floor or sheet of paper).</span></li>
                <li><b data-i18n="guide_lighting_b">Lighting:</b> <span data-i18n="guide_lighting">Even, diffuse lighting. Avoid harsh shadows on the foot.</span></li>
                <li><b data-i18n="guide_same_card_b">Same card:</b> <span data-i18n="guide_same_card">Use the same card across all six views for consistent scale.</span></li>
              </ul>
            </details>

            <div style="text-align:center;margin:6px 0 14px;font-size:0.85rem;color:var(--muted);">Tap each cell below to upload the photo for that view.</div>

            <div class="foot-side-label" data-i18n="left_foot">Left Foot</div>
            <div class="upload-grid" style="margin-bottom:16px;">
              <div class="upload-cell" id="cell-left_plantar" onclick="openPhotoSource('left_plantar')">
                <div class="validate-badge" id="badge-left_plantar" style="display:none"></div>
                <div class="card-warn-icon" id="cardwarn-left_plantar" style="display:none">&#128196; No card</div>
                <button type="button" class="sample-help-btn" onclick="event.stopPropagation();showSample('left','plantar')" title="View sample image">?</button>
                <div class="view-label" data-i18n="view_plantar">Plantar (sole)</div>
                <div class="view-hint" data-i18n="hint_plantar">Bottom of foot</div>
                <img class="preview-img" id="prev-left_plantar" alt="">
                <div class="file-name" id="fn-left_plantar"></div>
                <input type="file" name="left_plantar" id="input-left_plantar" accept="image/*" required onchange="markFile(this,'left_plantar')">
                <div class="camera-badge"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle></svg></div>
              </div>
              <div class="upload-cell" id="cell-left_dorsal" onclick="openPhotoSource('left_dorsal')">
                <div class="validate-badge" id="badge-left_dorsal" style="display:none"></div>
                <div class="card-warn-icon" id="cardwarn-left_dorsal" style="display:none">&#128196; No card</div>
                <button type="button" class="sample-help-btn" onclick="event.stopPropagation();showSample('left','dorsal')" title="View sample image">?</button>
                <div class="view-label" data-i18n="view_dorsal">Dorsal (top)</div>
                <div class="view-hint" data-i18n="hint_dorsal">Top of foot</div>
                <img class="preview-img" id="prev-left_dorsal" alt="">
                <div class="file-name" id="fn-left_dorsal"></div>
                <input type="file" name="left_dorsal" id="input-left_dorsal" accept="image/*" required onchange="markFile(this,'left_dorsal')">
                <div class="camera-badge"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle></svg></div>
              </div>
              <div class="upload-cell" id="cell-left_medial" onclick="openPhotoSource('left_medial')">
                <div class="validate-badge" id="badge-left_medial" style="display:none"></div>
                <div class="card-warn-icon" id="cardwarn-left_medial" style="display:none">&#128196; No card</div>
                <button type="button" class="sample-help-btn" onclick="event.stopPropagation();showSample('left','medial')" title="View sample image">?</button>
                <div class="view-label" data-i18n="view_medial">Medial (inner)</div>
                <div class="view-hint" data-i18n="hint_medial">Inner side</div>
                <img class="preview-img" id="prev-left_medial" alt="">
                <div class="file-name" id="fn-left_medial"></div>
                <input type="file" name="left_medial" id="input-left_medial" accept="image/*" required onchange="markFile(this,'left_medial')">
                <div class="camera-badge"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle></svg></div>
              </div>
            </div>

            <div class="foot-side-label" data-i18n="right_foot">Right Foot</div>
            <div class="upload-grid">
              <div class="upload-cell" id="cell-right_plantar" onclick="openPhotoSource('right_plantar')">
                <div class="validate-badge" id="badge-right_plantar" style="display:none"></div>
                <div class="card-warn-icon" id="cardwarn-right_plantar" style="display:none">&#128196; No card</div>
                <button type="button" class="sample-help-btn" onclick="event.stopPropagation();showSample('right','plantar')" title="View sample image">?</button>
                <div class="view-label" data-i18n="view_plantar">Plantar (sole)</div>
                <div class="view-hint" data-i18n="hint_plantar">Bottom of foot</div>
                <img class="preview-img" id="prev-right_plantar" alt="">
                <div class="file-name" id="fn-right_plantar"></div>
                <input type="file" name="right_plantar" id="input-right_plantar" accept="image/*" required onchange="markFile(this,'right_plantar')">
                <div class="camera-badge"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle></svg></div>
              </div>
              <div class="upload-cell" id="cell-right_dorsal" onclick="openPhotoSource('right_dorsal')">
                <div class="validate-badge" id="badge-right_dorsal" style="display:none"></div>
                <div class="card-warn-icon" id="cardwarn-right_dorsal" style="display:none">&#128196; No card</div>
                <button type="button" class="sample-help-btn" onclick="event.stopPropagation();showSample('right','dorsal')" title="View sample image">?</button>
                <div class="view-label" data-i18n="view_dorsal">Dorsal (top)</div>
                <div class="view-hint" data-i18n="hint_dorsal">Top of foot</div>
                <img class="preview-img" id="prev-right_dorsal" alt="">
                <div class="file-name" id="fn-right_dorsal"></div>
                <input type="file" name="right_dorsal" id="input-right_dorsal" accept="image/*" required onchange="markFile(this,'right_dorsal')">
                <div class="camera-badge"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle></svg></div>
              </div>
              <div class="upload-cell" id="cell-right_medial" onclick="openPhotoSource('right_medial')">
                <div class="validate-badge" id="badge-right_medial" style="display:none"></div>
                <div class="card-warn-icon" id="cardwarn-right_medial" style="display:none">&#128196; No card</div>
                <button type="button" class="sample-help-btn" onclick="event.stopPropagation();showSample('right','medial')" title="View sample image">?</button>
                <div class="view-label" data-i18n="view_medial">Medial (inner)</div>
                <div class="view-hint" data-i18n="hint_medial">Inner side</div>
                <img class="preview-img" id="prev-right_medial" alt="">
                <div class="file-name" id="fn-right_medial"></div>
                <input type="file" name="right_medial" id="input-right_medial" accept="image/*" required onchange="markFile(this,'right_medial')">
                <div class="camera-badge"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle></svg></div>
              </div>
            </div>
          </div>

          <!-- Camera-vs-gallery choice sheet, shared by all 6 photo cells -->
          <div class="photo-source-overlay" id="photo-source-overlay" onclick="if(event.target===this)closePhotoSource()">
            <div class="photo-source-sheet">
              <div class="photo-source-title" data-i18n="photo_add">Add photo</div>
              <button type="button" class="photo-source-btn" onclick="choosePhotoSource('camera')">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle></svg>
                <span data-i18n="photo_camera">Take Photo</span>
              </button>
              <button type="button" class="photo-source-btn" onclick="choosePhotoSource('gallery')">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
                <span data-i18n="photo_gallery">Choose from Gallery</span>
              </button>
              <button type="button" class="photo-source-cancel" data-i18n="photo_cancel" onclick="closePhotoSource()">Cancel</button>
            </div>
          </div>
          <input type="file" id="shared-camera-input" accept="image/*" capture="environment" style="display:none">
          <input type="file" id="shared-gallery-input" accept="image/*" style="display:none">

          <div class="panel">
            <div class="section-title" data-i18n="manual_measurements">Manual Measurements (Optional)</div>
            <p style="font-size:0.85rem;color:var(--muted);margin-bottom:12px;" data-i18n="manual_measurements_desc">Enter tape-measured values for comparison with AI estimates. All values in mm.</p>
            <table class="meas-table" style="width:100%">
              <thead><tr>
                <th data-i18n="meas_measurement">Measurement</th>
                <th data-i18n="meas_left">Left (cm)</th>
                <th data-i18n="meas_right">Right (cm)</th>
              </tr></thead>
              <tbody>
                <tr><td data-i18n="meas_foot_length">Foot length</td>
                    <td><input type="number" name="manual_foot_length_left" step="0.1" min="0" placeholder="—" style="width:80px"></td>
                    <td><input type="number" name="manual_foot_length_right" step="0.1" min="0" placeholder="—" style="width:80px"></td></tr>
                <tr><td data-i18n="meas_ball_girth">Ball girth</td>
                    <td><input type="number" name="manual_ball_girth_left" step="0.1" min="0" placeholder="—" style="width:80px"></td>
                    <td><input type="number" name="manual_ball_girth_right" step="0.1" min="0" placeholder="—" style="width:80px"></td></tr>
                <tr><td data-i18n="meas_instep_girth">Instep girth</td>
                    <td><input type="number" name="manual_instep_girth_left" step="0.1" min="0" placeholder="—" style="width:80px"></td>
                    <td><input type="number" name="manual_instep_girth_right" step="0.1" min="0" placeholder="—" style="width:80px"></td></tr>
                <tr><td data-i18n="meas_malleoli_height">Malleoli height</td>
                    <td><input type="number" name="manual_malleoli_height_left" step="0.1" min="0" placeholder="—" style="width:80px"></td>
                    <td><input type="number" name="manual_malleoli_height_right" step="0.1" min="0" placeholder="—" style="width:80px"></td></tr>
              </tbody>
            </table>
          </div>

          <div class="panel">
            <input type="hidden" name="camera_calib" value="">
            <div class="actions">
              <button class="btn-primary" id="submit-btn" type="submit" data-i18n="run_inference">Run Inference</button>
              <div id="status" class="status"></div>
              <div id="duplicate-warning-banner" style="display:none;margin-top:10px;padding:10px 14px;background:#fff3cd;border:1px solid #ffc107;border-radius:6px;font-size:0.92rem;color:#856404;"></div>
            </div>
            <div class="progress-wrap" id="progress-wrap">
              <div class="progress-bar"><div class="progress-fill" id="progress-fill"></div></div>
              <div class="progress-label" id="progress-label"></div>
            </div>
          </div>
        </form>

        <div id="result" class="result">
          <div class="panel">
            <div class="section-title" data-i18n="results">Results</div>
            <div class="result-header" id="result-header"></div>
            <div id="patient-info-summary"></div>
            <div class="sep"></div>
            <div id="meas-container"></div>
            <div id="warnings-container"></div>
            <div class="result-actions" id="result-actions"></div>
          </div>
          <div class="panel viz-section" id="viz-seg-panel" style="display:none;">
            <div class="section-title" data-i18n="segmentation_overlay">Segmentation Overlay</div>
            <div class="viz-grid" id="viz-seg-grid"></div>
          </div>
          <div class="panel viz-section" id="viz-lm-panel" style="display:none;">
            <div class="section-title" data-i18n="predicted_landmarks">Predicted Landmarks</div>
            <div class="viz-grid" id="viz-lm-grid"></div>
          </div>
          <div class="panel">
            <div id="json-container"></div>
          </div>
        </div>
      </div>

      <!-- ═══ PATIENT HISTORY ═══ -->
      <div id="sec-history" class="section">
        <div class="panel">
          <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:12px;">
            <div class="section-title" style="margin-bottom:0;" data-i18n="patient_history">Patient History</div>
            <button onclick="window.open('/api/export/csv')" class="btn-secondary" style="font-size:0.82rem;padding:6px 14px;">&#8595; Export CSV</button>
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;">
            <input id="hist-search" type="search" placeholder="Search name or patient ID…" oninput="filterHistory()" style="flex:1;min-width:160px;padding:7px 10px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink);font-size:0.88rem;">
            <label style="display:flex;align-items:center;gap:5px;font-size:0.84rem;color:var(--muted);">From <input id="hist-date-from" type="date" onchange="filterHistory()" style="padding:7px 8px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink);font-size:0.88rem;"></label>
            <label style="display:flex;align-items:center;gap:5px;font-size:0.84rem;color:var(--muted);">To <input id="hist-date-to" type="date" onchange="filterHistory()" style="padding:7px 8px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink);font-size:0.88rem;"></label>
          </div>
          <div id="history-content"></div>
        </div>
      </div>

      <!-- ═══ AGENT MANAGEMENT (admin only) ═══ -->
      <div id="sec-agents" class="section">
        <div class="panel">
          <div class="section-title" data-i18n="nav_agents">Agent Management</div>
          <div id="agents-content"><p style="color:var(--muted);"><span class="spinner"></span>Loading...</p></div>
        </div>
      </div>

      <!-- ═══ LANGUAGE ═══ -->
      <div id="sec-language" class="section">
        <div class="settings-card">
          <h3 data-i18n="language_preference">Language Preference</h3>
          <p data-i18n="select_language_desc">Select the display language for the application interface.</p>
          <select id="lang-select" onchange="setLanguage(this.value)" style="max-width:300px;padding:10px 14px;border:1px solid var(--line);border-radius:8px;font:inherit;font-size:0.92rem;">
            <option value="en">English</option>
            <option value="hi">हिन्दी (Hindi)</option>
            <option value="or">ଓଡ଼ିଆ (Odia)</option>
            <option value="te">తెలుగు (Telugu)</option>
            <option value="mr">मराठी (Marathi)</option>
          </select>
        </div>
      </div>

      <!-- ═══ HELP & SUPPORT ═══ -->
      <div id="sec-help" class="section">
        <div class="settings-card">
          <h3 data-i18n="help_support">Help & Support</h3>
          <p data-i18n="help_desc">Find answers to common questions about using Lepra 2.0.</p>
        </div>
        <div class="settings-card">
          <h3 data-i18n="faq_title">Frequently Asked Questions</h3>
          <details style="margin-bottom:10px;">
            <summary style="cursor:pointer;font-weight:600;color:var(--ink);font-size:0.92rem;padding:6px 0;" data-i18n="faq_q1">How do I capture foot images correctly?</summary>
            <p style="font-size:0.88rem;color:var(--muted);padding:8px 0 4px 0;" data-i18n="faq_a1">Place a standard credit/debit card flat on the same surface as the foot. Hold the camera perpendicular to the foot. Only the foot and card should be in the frame. Use even, diffuse lighting.</p>
          </details>
          <details style="margin-bottom:10px;">
            <summary style="cursor:pointer;font-weight:600;color:var(--ink);font-size:0.92rem;padding:6px 0;" data-i18n="faq_q2">What does "borrowed scale" mean?</summary>
            <p style="font-size:0.88rem;color:var(--muted);padding:8px 0 4px 0;" data-i18n="faq_a2">When the reference card is not detected in a particular view, the system borrows the scale (px/mm ratio) from another view of the same foot where the card was successfully detected.</p>
          </details>
          <details style="margin-bottom:10px;">
            <summary style="cursor:pointer;font-weight:600;color:var(--ink);font-size:0.92rem;padding:6px 0;" data-i18n="faq_q4">Why are some measurements marked as provisional?</summary>
            <p style="font-size:0.88rem;color:var(--muted);padding:8px 0 4px 0;" data-i18n="faq_a4">Ball girth and instep girth are estimated using width ratios rather than direct measurement, so they are marked with an asterisk (*) as provisional estimates.</p>
          </details>
        </div>
        <div class="settings-card">
          <h3 data-i18n="contact_support">Contact Support</h3>
          <p style="margin-bottom:8px;" data-i18n="contact_desc">For technical assistance, please contact the development team.</p>
          <p style="font-size:0.88rem;margin-bottom:4px;"><strong>Email:</strong> <a href="mailto:akhila.r@iihmrbangalore.edu.in" style="color:var(--accent);">akhila.r@iihmrbangalore.edu.in</a></p>
          <p style="font-size:0.88rem;"><strong>Email:</strong> <a href="mailto:admireiihmr@gmail.com" style="color:var(--accent);">admireiihmr@gmail.com</a></p>
        </div>
      </div>

      <!-- ═══ ABOUT US ═══ -->
      <div id="sec-about" class="section">
        <!-- Hero banner with team photo background -->
        <div style="position:relative;border-radius:16px;overflow:hidden;margin-bottom:24px;min-height:420px;display:flex;align-items:flex-end;">
          <img src="/samples/team_photo.png" onerror="this.parentElement.style.background='linear-gradient(135deg,#2563eb,#1d4ed8)'" alt="" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:center top;z-index:0;">
          <div style="position:absolute;inset:0;background:linear-gradient(to top,rgba(0,0,0,0.75) 0%,rgba(0,0,0,0.25) 50%,rgba(0,0,0,0.1) 100%);z-index:1;"></div>
          <div style="position:relative;z-index:2;padding:28px 32px;width:100%;">
            <div style="font-weight:900;font-size:1.3rem;color:#fff;letter-spacing:-0.5px;margin-bottom:4px;">IIHMR ADMIRE</div>
            <div style="font-size:0.8rem;color:rgba(255,255,255,0.8);margin-bottom:10px;">Centre for Advancing Digital Health</div>
            <div style="display:inline-block;padding:3px 12px;background:rgba(37,99,235,0.7);backdrop-filter:blur(4px);border-radius:20px;font-size:0.72rem;font-weight:700;color:#fff;letter-spacing:0.5px;text-transform:uppercase;">Collaborative Innovation</div>
          </div>
        </div>

        <!-- Intro card -->
        <div class="settings-card" style="margin-bottom:20px;">
          <h3 style="font-size:1.4rem;font-weight:800;color:var(--ink);margin-bottom:6px;">AI-Powered Foot Assessment <span style="color:var(--accent);">for Leprosy Care</span></h3>
          <p style="font-size:0.9rem;color:var(--ink);line-height:1.7;margin-bottom:14px;">
            Developed in collaboration with <strong>LEPRA Society</strong>, this system utilizes advanced computer vision to enable automated foot measurement. Our goal is to improve early detection and treatment planning through digital health innovation, making high-quality screening accessible to all.
          </p>
          <div class="about-grid-2" style="gap:16px;margin-top:16px;">
            <div style="display:flex;gap:12px;align-items:flex-start;">
              <div style="width:36px;height:36px;border-radius:8px;background:rgba(37,99,235,0.1);display:flex;align-items:center;justify-content:center;flex-shrink:0;">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v8M8 12h8"/></svg>
              </div>
              <div>
                <div style="font-weight:700;font-size:0.88rem;color:var(--ink);">Our Vision</div>
                <div style="font-size:0.82rem;color:var(--muted);line-height:1.5;">To advance digital health in transforming healthcare by improving quality of services and reducing inequity.</div>
              </div>
            </div>
            <div style="display:flex;gap:12px;align-items:flex-start;">
              <div style="width:36px;height:36px;border-radius:8px;background:rgba(37,99,235,0.1);display:flex;align-items:center;justify-content:center;flex-shrink:0;">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87L18.18 22 12 18.27 5.82 22 7 14.14l-5-4.87 6.91-1.01L12 2z"/></svg>
              </div>
              <div>
                <div style="font-weight:700;font-size:0.88rem;color:var(--ink);">Our Mission</div>
                <div style="font-size:0.82rem;color:var(--muted);line-height:1.5;">Advancing the application of digital health technologies through research, education, and innovation in AI/ML.</div>
              </div>
            </div>
          </div>
        </div>

        <!-- Core Verticals -->
        <div class="about-grid-4" style="gap:12px;margin-bottom:20px;">
          <div class="settings-card" style="text-align:center;padding:16px 10px;">
            <div style="width:36px;height:36px;border-radius:50%;background:rgba(37,99,235,0.1);display:flex;align-items:center;justify-content:center;margin:0 auto 8px;font-weight:800;color:var(--accent);font-size:0.9rem;">1</div>
            <div style="font-size:0.8rem;font-weight:600;color:var(--ink);">Research &amp; Development</div>
          </div>
          <div class="settings-card" style="text-align:center;padding:16px 10px;">
            <div style="width:36px;height:36px;border-radius:50%;background:rgba(37,99,235,0.1);display:flex;align-items:center;justify-content:center;margin:0 auto 8px;font-weight:800;color:var(--accent);font-size:0.9rem;">2</div>
            <div style="font-size:0.8rem;font-weight:600;color:var(--ink);">Incubation</div>
          </div>
          <div class="settings-card" style="text-align:center;padding:16px 10px;">
            <div style="width:36px;height:36px;border-radius:50%;background:rgba(37,99,235,0.1);display:flex;align-items:center;justify-content:center;margin:0 auto 8px;font-weight:800;color:var(--accent);font-size:0.9rem;">3</div>
            <div style="font-size:0.8rem;font-weight:600;color:var(--ink);">Digi Health Data &amp; AI Lab</div>
          </div>
          <div class="settings-card" style="text-align:center;padding:16px 10px;">
            <div style="width:36px;height:36px;border-radius:50%;background:rgba(37,99,235,0.1);display:flex;align-items:center;justify-content:center;margin:0 auto 8px;font-weight:800;color:var(--accent);font-size:0.9rem;">4</div>
            <div style="font-size:0.8rem;font-weight:600;color:var(--ink);">Digital Health Skilling</div>
          </div>
        </div>

        <!-- Team Section -->
        <div class="settings-card" style="margin-bottom:20px;">
          <h3 style="font-size:1.1rem;font-weight:800;color:var(--ink);margin-bottom:16px;">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2" style="vertical-align:text-bottom;margin-right:6px;"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/></svg>
            Meet The Team
          </h3>

          <!-- Core Development Team -->
          <div style="margin-bottom:18px;">
            <div style="font-size:0.75rem;font-weight:700;color:var(--accent);text-transform:uppercase;letter-spacing:1px;padding-bottom:6px;border-bottom:1px solid var(--line);margin-bottom:10px;">Core Development Team</div>
            <div class="about-grid-3" style="gap:10px;">
              <a href="https://www.linkedin.com/in/adith-vijay-a39511389/" target="_blank" rel="noopener" style="display:flex;justify-content:space-between;align-items:center;padding:12px 14px;border-radius:10px;border:1px solid var(--line);text-decoration:none;transition:all 0.2s;" onmouseover="this.style.borderColor='var(--accent)';this.style.boxShadow='0 2px 8px rgba(0,0,0,0.06)'" onmouseout="this.style.borderColor='var(--line)';this.style.boxShadow='none'">
                <div><div style="font-weight:600;font-size:0.88rem;color:var(--ink);">Adith Vijay</div><div style="font-size:0.76rem;color:var(--muted);">Core Developer</div></div>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="var(--muted)"><path d="M19 3a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h14m-.5 15.5v-5.3a3.26 3.26 0 00-3.26-3.26c-.85 0-1.84.52-2.32 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 011.4 1.4v4.93h2.79M6.88 8.56a1.68 1.68 0 001.68-1.68c0-.93-.75-1.69-1.68-1.69a1.69 1.69 0 00-1.69 1.69c0 .93.76 1.68 1.69 1.68m1.39 9.94v-8.37H5.5v8.37h2.77z"/></svg>
              </a>
              <a href="https://www.linkedin.com/in/rayampalli-akhila-reddy-670b652b8/" target="_blank" rel="noopener" style="display:flex;justify-content:space-between;align-items:center;padding:12px 14px;border-radius:10px;border:1px solid var(--line);text-decoration:none;transition:all 0.2s;" onmouseover="this.style.borderColor='var(--accent)';this.style.boxShadow='0 2px 8px rgba(0,0,0,0.06)'" onmouseout="this.style.borderColor='var(--line)';this.style.boxShadow='none'">
                <div><div style="font-weight:600;font-size:0.88rem;color:var(--ink);">Akhila R</div><div style="font-size:0.76rem;color:var(--muted);">Core Developer</div></div>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="var(--muted)"><path d="M19 3a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h14m-.5 15.5v-5.3a3.26 3.26 0 00-3.26-3.26c-.85 0-1.84.52-2.32 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 011.4 1.4v4.93h2.79M6.88 8.56a1.68 1.68 0 001.68-1.68c0-.93-.75-1.69-1.68-1.69a1.69 1.69 0 00-1.69 1.69c0 .93.76 1.68 1.69 1.68m1.39 9.94v-8.37H5.5v8.37h2.77z"/></svg>
              </a>
              <a href="https://www.linkedin.com/in/ankur-thakur-a95b89261/" target="_blank" rel="noopener" style="display:flex;justify-content:space-between;align-items:center;padding:12px 14px;border-radius:10px;border:1px solid var(--line);text-decoration:none;transition:all 0.2s;" onmouseover="this.style.borderColor='var(--accent)';this.style.boxShadow='0 2px 8px rgba(0,0,0,0.06)'" onmouseout="this.style.borderColor='var(--line)';this.style.boxShadow='none'">
                <div><div style="font-weight:600;font-size:0.88rem;color:var(--ink);">Ankur Thakur</div><div style="font-size:0.76rem;color:var(--muted);">Core Developer</div></div>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="var(--muted)"><path d="M19 3a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h14m-.5 15.5v-5.3a3.26 3.26 0 00-3.26-3.26c-.85 0-1.84.52-2.32 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 011.4 1.4v4.93h2.79M6.88 8.56a1.68 1.68 0 001.68-1.68c0-.93-.75-1.69-1.68-1.69a1.69 1.69 0 00-1.69 1.69c0 .93.76 1.68 1.69 1.68m1.39 9.94v-8.37H5.5v8.37h2.77z"/></svg>
              </a>
            </div>
          </div>

          <!-- Faculty & Technical Leadership -->
          <div style="margin-bottom:18px;">
            <div style="font-size:0.75rem;font-weight:700;color:var(--accent);text-transform:uppercase;letter-spacing:1px;padding-bottom:6px;border-bottom:1px solid var(--line);margin-bottom:10px;">Faculty &amp; Technical Leadership</div>
            <div class="about-grid-3" style="gap:10px;">
              <a href="https://www.linkedin.com/in/akash-prabhune-08ba5a61/" target="_blank" rel="noopener" style="display:flex;justify-content:space-between;align-items:center;padding:12px 14px;border-radius:10px;border:1px solid var(--line);text-decoration:none;transition:all 0.2s;" onmouseover="this.style.borderColor='var(--accent)';this.style.boxShadow='0 2px 8px rgba(0,0,0,0.06)'" onmouseout="this.style.borderColor='var(--line)';this.style.boxShadow='none'">
                <div><div style="font-weight:600;font-size:0.88rem;color:var(--ink);">Dr. Akash Prabhune</div><div style="font-size:0.76rem;color:var(--muted);">Asst. Professor &amp; Lead</div></div>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="var(--muted)"><path d="M19 3a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h14m-.5 15.5v-5.3a3.26 3.26 0 00-3.26-3.26c-.85 0-1.84.52-2.32 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 011.4 1.4v4.93h2.79M6.88 8.56a1.68 1.68 0 001.68-1.68c0-.93-.75-1.69-1.68-1.69a1.69 1.69 0 00-1.69 1.69c0 .93.76 1.68 1.69 1.68m1.39 9.94v-8.37H5.5v8.37h2.77z"/></svg>
              </a>
              <a href="https://www.linkedin.com/in/vinay-r-srihari-09023171/" target="_blank" rel="noopener" style="display:flex;justify-content:space-between;align-items:center;padding:12px 14px;border-radius:10px;border:1px solid var(--line);text-decoration:none;transition:all 0.2s;" onmouseover="this.style.borderColor='var(--accent)';this.style.boxShadow='0 2px 8px rgba(0,0,0,0.06)'" onmouseout="this.style.borderColor='var(--line)';this.style.boxShadow='none'">
                <div><div style="font-weight:600;font-size:0.88rem;color:var(--ink);">Mr. Vinay R Srihari</div><div style="font-size:0.76rem;color:var(--muted);">Technical Faculty</div></div>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="var(--muted)"><path d="M19 3a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h14m-.5 15.5v-5.3a3.26 3.26 0 00-3.26-3.26c-.85 0-1.84.52-2.32 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 011.4 1.4v4.93h2.79M6.88 8.56a1.68 1.68 0 001.68-1.68c0-.93-.75-1.69-1.68-1.69a1.69 1.69 0 00-1.69 1.69c0 .93.76 1.68 1.69 1.68m1.39 9.94v-8.37H5.5v8.37h2.77z"/></svg>
              </a>
              <a href="https://www.linkedin.com/in/dr-subodh-s-satheesh-7b1a75137/" target="_blank" rel="noopener" style="display:flex;justify-content:space-between;align-items:center;padding:12px 14px;border-radius:10px;border:1px solid var(--line);text-decoration:none;transition:all 0.2s;" onmouseover="this.style.borderColor='var(--accent)';this.style.boxShadow='0 2px 8px rgba(0,0,0,0.06)'" onmouseout="this.style.borderColor='var(--line)';this.style.boxShadow='none'">
                <div><div style="font-weight:600;font-size:0.88rem;color:var(--ink);">Dr. Subodh S Satheesh</div><div style="font-size:0.76rem;color:var(--muted);">Faculty Advisor</div></div>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="var(--muted)"><path d="M19 3a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h14m-.5 15.5v-5.3a3.26 3.26 0 00-3.26-3.26c-.85 0-1.84.52-2.32 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 011.4 1.4v4.93h2.79M6.88 8.56a1.68 1.68 0 001.68-1.68c0-.93-.75-1.69-1.68-1.69a1.69 1.69 0 00-1.69 1.69c0 .93.76 1.68 1.69 1.68m1.39 9.94v-8.37H5.5v8.37h2.77z"/></svg>
              </a>
            </div>
          </div>

          <!-- LEPRA Society Partners -->
          <div style="margin-bottom:18px;">
            <div style="font-size:0.75rem;font-weight:700;color:var(--accent);text-transform:uppercase;letter-spacing:1px;padding-bottom:6px;border-bottom:1px solid var(--line);margin-bottom:10px;">LEPRA Society Partners</div>
            <div class="about-grid-2" style="gap:10px;">
              <a href="https://www.linkedin.com/in/k-arun-kumar-head-programmes-612011289/" target="_blank" rel="noopener" style="display:flex;justify-content:space-between;align-items:center;padding:12px 14px;border-radius:10px;border:1px solid var(--line);text-decoration:none;transition:all 0.2s;" onmouseover="this.style.borderColor='var(--accent)';this.style.boxShadow='0 2px 8px rgba(0,0,0,0.06)'" onmouseout="this.style.borderColor='var(--line)';this.style.boxShadow='none'">
                <div><div style="font-weight:600;font-size:0.88rem;color:var(--ink);">K Arun Kumar</div><div style="font-size:0.76rem;color:var(--muted);">Head - Programmes</div></div>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="var(--muted)"><path d="M19 3a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h14m-.5 15.5v-5.3a3.26 3.26 0 00-3.26-3.26c-.85 0-1.84.52-2.32 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 011.4 1.4v4.93h2.79M6.88 8.56a1.68 1.68 0 001.68-1.68c0-.93-.75-1.69-1.68-1.69a1.69 1.69 0 00-1.69 1.69c0 .93.76 1.68 1.69 1.68m1.39 9.94v-8.37H5.5v8.37h2.77z"/></svg>
              </a>
              <a href="https://www.linkedin.com/in/khyathi-reddy-5a666b180/" target="_blank" rel="noopener" style="display:flex;justify-content:space-between;align-items:center;padding:12px 14px;border-radius:10px;border:1px solid var(--line);text-decoration:none;transition:all 0.2s;" onmouseover="this.style.borderColor='var(--accent)';this.style.boxShadow='0 2px 8px rgba(0,0,0,0.06)'" onmouseout="this.style.borderColor='var(--line)';this.style.boxShadow='none'">
                <div><div style="font-weight:600;font-size:0.88rem;color:var(--ink);">Dr. Khyathi Reddy</div><div style="font-size:0.76rem;color:var(--muted);">Medical Expert</div></div>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="var(--muted)"><path d="M19 3a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h14m-.5 15.5v-5.3a3.26 3.26 0 00-3.26-3.26c-.85 0-1.84.52-2.32 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 011.4 1.4v4.93h2.79M6.88 8.56a1.68 1.68 0 001.68-1.68c0-.93-.75-1.69-1.68-1.69a1.69 1.69 0 00-1.69 1.69c0 .93.76 1.68 1.69 1.68m1.39 9.94v-8.37H5.5v8.37h2.77z"/></svg>
              </a>
            </div>
          </div>

          <!-- Senior Advisors -->
          <div>
            <div style="font-size:0.75rem;font-weight:700;color:var(--accent);text-transform:uppercase;letter-spacing:1px;padding-bottom:6px;border-bottom:1px solid var(--line);margin-bottom:10px;">Senior Advisors</div>
            <div class="about-grid-2" style="gap:10px;">
              <a href="https://www.linkedin.com/in/ushamanjunath/" target="_blank" rel="noopener" style="display:flex;justify-content:space-between;align-items:center;padding:12px 14px;border-radius:10px;border:1px solid var(--line);text-decoration:none;transition:all 0.2s;" onmouseover="this.style.borderColor='var(--accent)';this.style.boxShadow='0 2px 8px rgba(0,0,0,0.06)'" onmouseout="this.style.borderColor='var(--line)';this.style.boxShadow='none'">
                <div><div style="font-weight:600;font-size:0.88rem;color:var(--ink);">Dr. Usha Manjunath</div><div style="font-size:0.76rem;color:var(--muted);">Professor &amp; Director</div></div>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="var(--muted)"><path d="M19 3a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h14m-.5 15.5v-5.3a3.26 3.26 0 00-3.26-3.26c-.85 0-1.84.52-2.32 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 011.4 1.4v4.93h2.79M6.88 8.56a1.68 1.68 0 001.68-1.68c0-.93-.75-1.69-1.68-1.69a1.69 1.69 0 00-1.69 1.69c0 .93.76 1.68 1.69 1.68m1.39 9.94v-8.37H5.5v8.37h2.77z"/></svg>
              </a>
              <a href="https://www.linkedin.com/in/s-d-gupta-7511a516/" target="_blank" rel="noopener" style="display:flex;justify-content:space-between;align-items:center;padding:12px 14px;border-radius:10px;border:1px solid var(--line);text-decoration:none;transition:all 0.2s;" onmouseover="this.style.borderColor='var(--accent)';this.style.boxShadow='0 2px 8px rgba(0,0,0,0.06)'" onmouseout="this.style.borderColor='var(--line)';this.style.boxShadow='none'">
                <div><div style="font-weight:600;font-size:0.88rem;color:var(--ink);">Dr. Shivdutta Gupta</div><div style="font-size:0.76rem;color:var(--muted);">Senior Advisor</div></div>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="var(--muted)"><path d="M19 3a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h14m-.5 15.5v-5.3a3.26 3.26 0 00-3.26-3.26c-.85 0-1.84.52-2.32 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 011.4 1.4v4.93h2.79M6.88 8.56a1.68 1.68 0 001.68-1.68c0-.93-.75-1.69-1.68-1.69a1.69 1.69 0 00-1.69 1.69c0 .93.76 1.68 1.69 1.68m1.39 9.94v-8.37H5.5v8.37h2.77z"/></svg>
              </a>
            </div>
          </div>
        </div>

        <!-- Contact Footer -->
        <div class="settings-card">
          <div class="about-grid-21" style="gap:24px;">
            <div>
              <div style="font-weight:900;font-size:1.05rem;color:var(--accent);margin-bottom:8px;">IIHMR ADMIRE</div>
              <p style="font-size:0.84rem;color:var(--muted);line-height:1.6;">Centre for Advancing Digital Health at IIHMR Bangalore. Dedicated to transforming healthcare through digital technologies, AI, and machine learning.</p>
            </div>
            <div>
              <div style="font-weight:700;font-size:0.88rem;color:var(--ink);margin-bottom:8px;">Contact Details</div>
              <div style="font-size:0.82rem;color:var(--muted);line-height:2;">
                <div>IIHMR Bangalore &bull; Electronic City Phase-I, Bangalore &ndash; 560105</div>
                <div>Phone: 080-61133800</div>
                <div><a href="mailto:admire.digihealth@iihmrbangalore.edu.in" style="color:var(--accent);font-weight:500;">admire.digihealth@iihmrbangalore.edu.in</a></div>
              </div>
            </div>
          </div>
          <div style="margin-top:18px;padding-top:12px;border-top:1px solid var(--line);text-align:center;font-size:0.74rem;color:var(--muted);">
            &copy; 2026 ADMIRE Centre - IIHMR Bangalore. All rights reserved.
          </div>
        </div>
      </div>

      <!-- ═══ THEME ═══ -->
      <div id="sec-theme" class="section">
        <div class="settings-card">
          <h3 data-i18n="theme_preference">Theme Preference</h3>
          <p data-i18n="choose_theme">Choose the visual theme for the application.</p>
          <div class="theme-options">
            <div class="theme-card active" id="theme-light" onclick="setTheme('light')">
              <div class="theme-preview" style="background:#f0f2f5;"></div>
              <div class="theme-name" data-i18n="theme_light">Light</div>
            </div>
            <div class="theme-card" id="theme-dark" onclick="setTheme('dark')">
              <div class="theme-preview" style="background:#111827;"></div>
              <div class="theme-name" data-i18n="theme_dark">Dark</div>
            </div>
          </div>
        </div>
      </div>

    </div><!-- .content -->
  <!-- Sample image modal -->
  <div class="sample-modal-overlay" id="sample-modal-overlay" onclick="closeSample()">
    <div class="sample-modal" onclick="event.stopPropagation()">
      <button class="sample-modal-close" onclick="closeSample()">&times;</button>
      <h3 id="sample-modal-title" data-i18n="sample_image">Sample Image</h3>
      <img id="sample-modal-img" src="" alt="Sample">
      <div class="sample-note" data-i18n="sample_note">Place the reference card near the foot as shown above.</div>
    </div>
  </div>

  <div id="sidebar-backdrop" class="sidebar-backdrop"></div>
  </div><!-- .main-area -->

  <script>
    // Log uncaught errors to the console for debugging instead of surfacing
    // a raw stack trace to end users — a full-page red banner with internal
    // error details has no place in a production clinical tool.
    window.onerror = function(msg, url, line, col, err) {
      console.error('Uncaught error (line ' + line + '):', msg, err);
    };
  </script>
  <script>
    // ═══════════════════════════════════════════════════════════
    // TRANSLATIONS
    // ═══════════════════════════════════════════════════════════
    const TRANSLATIONS = {
      en: {
        // Sidebar
        nav_overview:"OVERVIEW", nav_dashboard:"Dashboard", nav_prediction:"Measurement Estimation",
        nav_history:"Patient History", nav_settings:"SETTINGS", nav_language:"Language",
        nav_help:"Help & Support", nav_theme:"Theme", nav_about:"About Us", nav_agents:"Agent Management",
        // Dashboard stats
        stat_total_predictions:"Total Estimations", stat_successful_runs:"Completed Estimations",
        stat_last_run:"Last Run", stat_avg_time:"Avg. Processing Time",
        recent_predictions:"Recent Estimations",
        patient_history:"Patient History",
        btn_new_patient:"New Patient",
        lbl_reference_type:"Reference Object Used", ref_card:"Standard Debit/Credit Card", ref_coin_5:"5 Rs Coin", ref_coin_10:"10 Rs Coin", ref_aruco:"ArUco Marker Card",
        no_predictions_yet:"No estimations yet. Go to Measurement Estimation to run your first.",
        // Dashboard table headers
        th_patient:"Patient", th_date:"Date", th_foot_length_lr:"Foot Length (L/R)",
        th_run_id:"Run ID", th_actions:"Actions",
        // Patient form
        patient_information:"Patient Information",
        lbl_patient_id:"Patient ID", lbl_patient_name:"Patient Name", lbl_age:"Age", lbl_gender:"Gender",
        lbl_abha_id:"ABHA ID", lbl_aadhar_id:"Aadhar Number", lbl_diabetes:"Diabetes", lbl_amputated_toes:"Amputated Toes",
        lbl_disease_type:"Disease Type", opt_leprosy:"Leprosy", opt_lf:"Lymphatic Filariasis (LF)",
        lbl_who_grade:"WHO Disability Grade", opt_grade_none:"None", opt_grade_1:"Grade 1", opt_grade_2:"Grade 2", opt_grade_3:"Grade 3", opt_grade_4:"Grade 4",
        lbl_exam_date:"Date of Examination", lbl_capture_center:"Capture Center", lbl_referring_doctor:"Referring Doctor",
        lbl_district:"District", lbl_village:"Village", lbl_captured_by:"Captured By", opt_other_staff:"Other (not in list)",
        lbl_clinical_notes:"Clinical Notes", lbl_phone:"Phone Number",
        ph_full_name:"Full name", ph_years:"Years", ph_hospital:"Hospital / clinic name", ph_phone:"+91 XXXXX XXXXX", ph_aadhar:"XXXX XXXX XXXX", ph_village:"Village name",
        manual_measurements:"Manual Measurements (Optional)", manual_measurements_desc:"Enter tape-measured values for comparison with AI estimates. All values in cm.",
        ph_clinical_notes:"Any relevant history, deformities, symptoms...",
        opt_select:"Select", opt_male:"Male", opt_female:"Female", opt_other:"Other",
        opt_yes:"Yes", opt_no:"No",
        // Foot images
        foot_images:"Foot Images", image_guidelines:"Image Capture Guidelines",
        guide_ref_card_b:"Reference card:", guide_ref_card:"Place a standard credit/debit card flat on the same surface as the foot \u2014 never hold it in hand.",
        guide_camera_b:"Camera angle:", guide_camera:"Hold the camera perpendicular \u2014 directly above for plantar, straight-on for dorsal and medial.",
        guide_framing_b:"Framing:", guide_framing:"Only the foot and card should be visible. No face, hands, or other body parts in the frame.",
        guide_background_b:"Background:", guide_background:"Plain, light-coloured surface (white / light grey floor or sheet of paper).",
        guide_lighting_b:"Lighting:", guide_lighting:"Even, diffuse lighting. Avoid harsh shadows on the foot.",
        guide_same_card_b:"Same card:", guide_same_card:"Use the same card across all six views for consistent scale.",
        left_foot:"Left Foot", right_foot:"Right Foot",
        view_plantar:"Plantar (sole)", view_dorsal:"Dorsal (top)", view_medial:"Medial (inner)",
        hint_plantar:"Bottom of foot", hint_dorsal:"Top of foot", hint_medial:"Inner side",
        // Settings & buttons
        settings:"Settings", allow_borrowed_scale:"Allow borrowed scale", lenient_mode:"Lenient mode",
        run_inference:"Run Inference",
        // Results
        results:"Results", segmentation_overlay:"Segmentation Overlay", predicted_landmarks:"Predicted Landmarks",
        btn_print_pdf:"Print / Download PDF", btn_download_json:"Download JSON",
        // Measurement labels
        meas_foot_length:"Foot length", meas_forefoot_width:"Forefoot width",
        meas_heel_width:"Heel width", meas_midfoot_width:"Midfoot width",
        meas_toe_axis:"Toe axis angle", meas_ball_girth:"Ball girth", meas_instep_girth:"Instep girth",
        meas_malleoli_height:"Malleoli height",
        meas_measurement:"Measurement", meas_left:"Left", meas_right:"Right",
        meas_provisional:"Provisional estimates based on width ratios.",
        meas_estimated_note:"Quality is <b>{q}</b>. Measurements shown are estimates and may be less accurate.",
        meas_estimated_prefix:"Note:",
        // Footwear preparation (technician)
        tech_table_title:"Footwear Preparation Values",
        tech_foot_length_plus2:"Foot Length (+2 cm)",
        tech_ball_girth_60pct:"Ball Girth (60%)",
        tech_instep_girth_85pct:"Instep Girth (85%)",
        tech_malleoli_height:"Height of Malleoli",
        tech_explainer:"Adjustments applied: foot length +2 cm, ball girth ×60%, instep girth ×85%. Used by technicians for last preparation.",
        tech_from_manual:"from manual",
        // Photo Quality Report (clinician-facing rejection reasons)
        quality_report_title:"Photo Quality Report",
        quality_summary_rejected:"{n} photo(s) had problems and could not be used",
        quality_summary_degraded:"All photos used, but {n} had reduced quality",
        quality_report_footnote:"Tip: missing measurements appear as “—”. Retake the photos listed above using the suggested fix to restore them.",
        view_left_plantar:"Left Plantar",
        view_left_dorsal:"Left Dorsal",
        view_left_medial:"Left Medial",
        view_right_plantar:"Right Plantar",
        view_right_dorsal:"Right Dorsal",
        view_right_medial:"Right Medial",
        // Progress
        stage_preprocessing:"Preprocessing images", stage_segmentation:"Segmenting",
        stage_reference:"Detecting reference scale", stage_landmarks:"Detecting landmarks",
        stage_geometry:"Computing measurements", stage_complete:"Done",
        status_uploading:"Uploading\u2026", status_running:"Processing\u2026", status_complete:"Estimation complete.",
        // History
        inference_history:"Patient History", patient_history:"Patient History", no_runs_found:"No patient records found.",
        history_loading:"Loading...", history_failed:"Failed to load history.",
        // Language
        language_preference:"Language Preference", select_language_desc:"Select the display language for the application interface.",
        // Help
        help_support:"Help & Support", help_desc:"Find answers to common questions about using Lepra 2.0.",
        faq_title:"Frequently Asked Questions",
        faq_q1:"How do I capture foot images correctly?",
        faq_a1:"Place a standard credit/debit card flat on the same surface as the foot. Hold the camera perpendicular to the foot. Only the foot and card should be in the frame. Use even, diffuse lighting.",
        faq_q2:'What does "borrowed scale" mean?',
        faq_a2:"When the reference card is not detected in a particular view, the system borrows the scale (px/mm ratio) from another view of the same foot where the card was successfully detected.",
        faq_q3:'What is "trusted" vs "degraded" quality?',
        faq_a3:'"Trusted" means all views had good reference card detection and mask quality. "Degraded" means some views had issues (borrowed scale, rejected masks), so measurements may be less accurate.',
        faq_q4:"Why are some measurements marked as provisional?",
        faq_a4:"Ball girth and instep girth are estimated using width ratios rather than direct measurement, so they are marked with an asterisk (*) as provisional estimates.",
        contact_support:"Contact Support", contact_desc:"For technical assistance, please contact the development team.",
        // Theme
        theme_preference:"Theme Preference", choose_theme:"Choose the visual theme for the application.",
        theme_light:"Light", theme_dark:"Dark",
        // Sample modal
        sample_image:"Sample Image", sample_note:"Place the reference card near the foot as shown above.",
        // Profile
        administrator:"Administrator", system_admin:"System Admin", logout:"Logout",
        // Warnings
        warn_mask_rejected:"mask rejected", warn_borrowed_scale:"no reference card detected \u2014 using borrowed scale",
        warn_poor_card:"poor card detection quality", warn_title:"View Quality Warnings",
        // Misc
        full_json_output:"Full JSON output",
        // Photo source sheet
        photo_add:"Add photo", photo_camera:"Take Photo", photo_gallery:"Choose from Gallery", photo_cancel:"Cancel"
      },
      hi: {
        nav_overview:"अवलोकन", nav_dashboard:"डैशबोर्ड", nav_prediction:"माप अनुमान",
        nav_history:"रोगी इतिहास", nav_settings:"सेटिंग्स", nav_language:"भाषा",
        nav_help:"सहायता और समर्थन", nav_theme:"थीम",
        stat_total_predictions:"कुल अनुमान", stat_successful_runs:"पूर्ण अनुमान",
        stat_last_run:"अंतिम रन",
        recent_predictions:"हाल की भविष्यवाणियाँ",
        no_predictions_yet:"अभी तक कोई भविष्यवाणी नहीं। अपना पहला अनुमान चलाने के लिए मॉडल भविष्यवाणी पर जाएं।",
        th_patient:"रोगी", th_date:"तारीख", th_foot_length_lr:"पैर की लंबाई (बा/दा)",
        th_run_id:"रन ID", th_actions:"कार्रवाई",
        patient_information:"रोगी की जानकारी",
        lbl_patient_id:"रोगी ID", lbl_patient_name:"रोगी का नाम", lbl_age:"आयु", lbl_gender:"लिंग",
        lbl_abha_id:"ABHA ID", lbl_aadhar_id:"Aadhar Number", lbl_diabetes:"मधुमेह", lbl_amputated_toes:"कटे हुए अंगूठे",
        lbl_disease_type:"रोग का प्रकार", opt_leprosy:"कुष्ठ रोग", opt_lf:"लसीका फाइलेरिया (एलएफ)",
        lbl_who_grade:"WHO Disability Grade", opt_grade_none:"None", opt_grade_1:"Grade 1", opt_grade_2:"Grade 2", opt_grade_3:"Grade 3", opt_grade_4:"Grade 4",
        lbl_exam_date:"परीक्षा की तारीख", lbl_capture_center:"कैप्चर केंद्र", lbl_referring_doctor:"रेफर करने वाले डॉक्टर",
        lbl_district:"District", lbl_village:"Village", lbl_captured_by:"Captured By", opt_other_staff:"Other (not in list)",
        lbl_clinical_notes:"नैदानिक नोट्स", lbl_phone:"Phone Number",
        ph_full_name:"पूरा नाम", ph_years:"वर्ष", ph_hospital:"अस्पताल / क्लिनिक का नाम", ph_phone:"+91 XXXXX XXXXX", ph_aadhar:"XXXX XXXX XXXX", ph_village:"Village name",
        manual_measurements:"Manual Measurements (Optional)", manual_measurements_desc:"Enter tape-measured values for comparison with AI estimates. All values in cm.",
        ph_clinical_notes:"कोई भी प्रासंगिक इतिहास, विकृतियाँ, लक्षण...",
        opt_select:"चुनें", opt_male:"पुरुष", opt_female:"महिला", opt_other:"अन्य",
        opt_yes:"हाँ", opt_no:"नहीं",
        foot_images:"पैर की तस्वीरें", image_guidelines:"छवि कैप्चर दिशानिर्देश",
        guide_ref_card_b:"संदर्भ कार्ड:", guide_ref_card:"एक मानक क्रेडिट/डेबिट कार्ड पैर के समान सतह पर सपाट रखें — कभी हाथ में न पकड़ें।",
        guide_camera_b:"कैमरा कोण:", guide_camera:"कैमरा लंबवत पकड़ें — प्लांटर के लिए सीधे ऊपर, डोर्सल और मीडियल के लिए सीधे सामने।",
        guide_framing_b:"फ्रेमिंग:", guide_framing:"केवल पैर और कार्ड दिखाई देना चाहिए। फ्रेम में कोई चेहरा, हाथ या अन्य शरीर के अंग नहीं।",
        guide_background_b:"पृष्ठभूमि:", guide_background:"सादी, हल्के रंग की सतह (सफेद / हल्के भूरे रंग का फर्श या कागज)।",
        guide_lighting_b:"प्रकाश:", guide_lighting:"समान, विसरित प्रकाश। पैर पर कठोर छाया से बचें।",
        guide_same_card_b:"एक ही कार्ड:", guide_same_card:"सभी छह दृश्यों में एक ही कार्ड का उपयोग करें।",
        left_foot:"बायाँ पैर", right_foot:"दायाँ पैर",
        view_plantar:"प्लांटर (तलवा)", view_dorsal:"डोर्सल (ऊपर)", view_medial:"मीडियल (अंदर)",
        hint_plantar:"पैर का नीचे", hint_dorsal:"पैर का ऊपर", hint_medial:"अंदर की ओर",
        settings:"सेटिंग्स", allow_borrowed_scale:"उधार स्केल की अनुमति", lenient_mode:"उदार मोड",
        run_inference:"अनुमान चलाएँ",
        results:"परिणाम", segmentation_overlay:"विभाजन ओवरले", predicted_landmarks:"अनुमानित लैंडमार्क",
        btn_print_pdf:"PDF प्रिंट / डाउनलोड करें", btn_download_json:"JSON डाउनलोड करें",
        meas_foot_length:"पैर की लंबाई", meas_forefoot_width:"अग्रपाद चौड़ाई",
        meas_heel_width:"एड़ी चौड़ाई", meas_midfoot_width:"मध्यपाद चौड़ाई",
        meas_toe_axis:"पैर की अंगुली अक्ष कोण", meas_ball_girth:"बॉल परिधि", meas_instep_girth:"इंस्टेप परिधि",
        meas_malleoli_height:"मैलिओलाई ऊंचाई",
        meas_measurement:"माप", meas_left:"बायाँ", meas_right:"दायाँ",
        meas_provisional:"चौड़ाई अनुपात पर आधारित अनंतिम अनुमान।",
        // Footwear preparation (technician)
        tech_table_title:"जूता तैयारी मान",
        tech_foot_length_plus2:"पैर की लंबाई (+2 सेमी)",
        tech_ball_girth_60pct:"बॉल परिधि (60%)",
        tech_instep_girth_85pct:"इंस्टेप परिधि (85%)",
        tech_malleoli_height:"मैलिओलाई ऊंचाई",
        tech_explainer:"समायोजन: पैर की लंबाई +2 सेमी, बॉल परिधि ×60%, इंस्टेप परिधि ×85%। तकनीशियनों द्वारा लास्ट तैयारी के लिए उपयोग किया जाता है।",
        tech_from_manual:"मैनुअल से",
        meas_estimated_note:"गुणवत्ता <b>{q}</b> है। दिखाए गए माप अनुमान हैं और कम सटीक हो सकते हैं।",
        meas_estimated_prefix:"नोट:",
        stage_preprocessing:"छवियों को प्रीप्रोसेस कर रहा है", stage_segmentation:"विभाजन कर रहा है",
        stage_reference:"संदर्भ स्केल का पता लगा रहा है", stage_landmarks:"लैंडमार्क का पता लगा रहा है",
        stage_geometry:"माप की गणना कर रहा है", stage_complete:"पूर्ण",
        status_uploading:"अपलोड हो रहा है\u2026", status_running:"पाइपलाइन चल रही है\u2026", status_complete:"अनुमान पूर्ण।",
        inference_history:"रोगी इतिहास", patient_history:"रोगी इतिहास", no_runs_found:"कोई रोगी रिकॉर्ड नहीं मिला।",
        history_loading:"लोड हो रहा है...", history_failed:"इतिहास लोड करने में विफल।",
        language_preference:"भाषा वरीयता", select_language_desc:"एप्लिकेशन इंटरफेस की प्रदर्शन भाषा चुनें।",
        help_support:"सहायता और समर्थन", help_desc:"Lepra 2.0 का उपयोग करने के बारे में सामान्य प्रश्नों के उत्तर खोजें।",
        faq_title:"अक्सर पूछे जाने वाले प्रश्न",
        faq_q1:"पैर की तस्वीरें सही तरीके से कैसे कैप्चर करें?",
        faq_a1:"एक मानक क्रेडिट/डेबिट कार्ड पैर के समान सतह पर सपाट रखें। कैमरा पैर के लंबवत पकड़ें। फ्रेम में केवल पैर और कार्ड होना चाहिए। समान, विसरित प्रकाश का उपयोग करें।",
        faq_q2:'"उधार स्केल" का क्या मतलब है?',
        faq_a2:"जब किसी विशेष दृश्य में संदर्भ कार्ड का पता नहीं चलता, तो सिस्टम उसी पैर के दूसरे दृश्य से स्केल (px/mm अनुपात) उधार लेता है।",
        faq_q3:'"विश्वसनीय" बनाम "निम्नीकृत" गुणवत्ता क्या है?',
        faq_a3:'"विश्वसनीय" का मतलब है कि सभी दृश्यों में अच्छा संदर्भ कार्ड पहचान था। "निम्नीकृत" का मतलब है कि कुछ दृश्यों में समस्याएं थीं।',
        faq_q4:"कुछ माप अनंतिम क्यों चिह्नित हैं?",
        faq_a4:"बॉल परिधि और इंस्टेप परिधि का अनुमान चौड़ाई अनुपात से लगाया जाता है, इसलिए उन्हें तारांकन (*) के साथ अनंतिम अनुमान के रूप में चिह्नित किया जाता है।",
        contact_support:"समर्थन से संपर्क करें", contact_desc:"तकनीकी सहायता के लिए, कृपया विकास टीम से संपर्क करें।",
        theme_preference:"थीम वरीयता", choose_theme:"एप्लिकेशन के लिए विज़ुअल थीम चुनें।",
        theme_light:"लाइट", theme_dark:"डार्क",
        sample_image:"नमूना छवि", sample_note:"संदर्भ कार्ड को ऊपर दिखाए अनुसार पैर के पास रखें।",
        administrator:"प्रशासक", system_admin:"सिस्टम एडमिन", logout:"लॉगआउट",
        warn_mask_rejected:"मास्क अस्वीकृत", warn_borrowed_scale:"कोई संदर्भ कार्ड नहीं मिला — उधार स्केल का उपयोग",
        warn_poor_card:"कार्ड पहचान गुणवत्ता खराब", warn_title:"दृश्य गुणवत्ता चेतावनियाँ",
        full_json_output:"पूर्ण JSON आउटपुट",
        photo_add:"फोटो जोड़ें", photo_camera:"फोटो लें", photo_gallery:"गैलरी से चुनें", photo_cancel:"रद्द करें"
      },
      or: {
        nav_overview:"ସାରାଂଶ", nav_dashboard:"ଡ୍ୟାସବୋର୍ଡ", nav_prediction:"ମାପ ଆକଳନ",
        nav_history:"ରୋଗୀ ଇତିହାସ", nav_settings:"ସେଟିଂସ୍", nav_language:"ଭାଷା",
        nav_help:"ସାହାଯ୍ୟ ଏବଂ ସମର୍ଥନ", nav_theme:"ଥିମ୍",
        stat_total_predictions:"ମୋଟ ଆକଳନ", stat_successful_runs:"ସମ୍ପୂର୍ଣ୍ଣ ଆକଳନ",
        stat_last_run:"ଶେଷ ରନ୍",
        recent_predictions:"ସାମ୍ପ୍ରତିକ ଭବିଷ୍ୟବାଣୀ",
        no_predictions_yet:"ଏପର୍ଯ୍ୟନ୍ତ କୌଣସି ଭବିଷ୍ୟବାଣୀ ନାହିଁ। ଆପଣଙ୍କ ପ୍ରଥମ ଅନୁମାନ ଚଲାଇବା ପାଇଁ ମଡେଲ ଭବିଷ୍ୟବାଣୀକୁ ଯାଆନ୍ତୁ।",
        th_patient:"ରୋଗୀ", th_date:"ତାରିଖ", th_foot_length_lr:"ପାଦ ଲମ୍ବ (ବା/ଡା)",
        th_run_id:"ରନ୍ ID", th_actions:"କାର୍ଯ୍ୟ",
        patient_information:"ରୋଗୀ ତଥ୍ୟ",
        lbl_patient_id:"ରୋଗୀ ID", lbl_patient_name:"ରୋଗୀ ନାମ", lbl_age:"ବୟସ", lbl_gender:"ଲିଙ୍ଗ",
        lbl_abha_id:"ABHA ID", lbl_aadhar_id:"Aadhar Number", lbl_diabetes:"ମଧୁମେହ", lbl_amputated_toes:"କଟା ଆଙ୍ଗୁଠି",
        lbl_disease_type:"ରୋଗ ପ୍ରକାର", opt_leprosy:"କୁଷ୍ଠ ରୋଗ", opt_lf:"ଲିମ୍ଫାଟିକ୍ ଫାଇଲାରିଆସିସ୍ (LF)",
        lbl_who_grade:"WHO Disability Grade", opt_grade_none:"None", opt_grade_1:"Grade 1", opt_grade_2:"Grade 2", opt_grade_3:"Grade 3", opt_grade_4:"Grade 4",
        lbl_exam_date:"ପରୀକ୍ଷା ତାରିଖ", lbl_capture_center:"କ୍ୟାପଚର କେନ୍ଦ୍ର", lbl_referring_doctor:"ରେଫର କରୁଥିବା ଡାକ୍ତର",
        lbl_district:"District", lbl_village:"Village", lbl_captured_by:"Captured By", opt_other_staff:"Other (not in list)",
        lbl_clinical_notes:"ନୈଦାନିକ ନୋଟ୍ସ", lbl_phone:"Phone Number",
        ph_full_name:"ପୂରା ନାମ", ph_years:"ବର୍ଷ", ph_hospital:"ହସ୍ପିଟାଲ / କ୍ଲିନିକ ନାମ", ph_phone:"+91 XXXXX XXXXX", ph_aadhar:"XXXX XXXX XXXX", ph_village:"Village name",
        manual_measurements:"Manual Measurements (Optional)", manual_measurements_desc:"Enter tape-measured values for comparison with AI estimates. All values in cm.",
        ph_clinical_notes:"ଯେକୌଣସି ପ୍ରାସଙ୍ଗିକ ଇତିହାସ, ବିକୃତି, ଲକ୍ଷଣ...",
        opt_select:"ବାଛନ୍ତୁ", opt_male:"ପୁରୁଷ", opt_female:"ମହିଳା", opt_other:"ଅନ୍ୟ",
        opt_yes:"ହଁ", opt_no:"ନା",
        foot_images:"ପାଦ ଛବି", image_guidelines:"ଛବି କ୍ୟାପଚର ନିର୍ଦ୍ଦେଶାବଳୀ",
        guide_ref_card_b:"ସନ୍ଦର୍ଭ କାର୍ଡ:", guide_ref_card:"ଏକ ମାନକ କ୍ରେଡିଟ/ଡେବିଟ କାର୍ଡ ପାଦ ସହ ସମାନ ସତହରେ ସମତଳ ରଖନ୍ତୁ।",
        guide_camera_b:"କ୍ୟାମେରା କୋଣ:", guide_camera:"କ୍ୟାମେରା ଲମ୍ବବତ ଧରନ୍ତୁ।",
        guide_framing_b:"ଫ୍ରେମିଂ:", guide_framing:"କେବଳ ପାଦ ଏବଂ କାର୍ଡ ଦେଖାଯିବା ଉଚିତ।",
        guide_background_b:"ପୃଷ୍ଠଭୂମି:", guide_background:"ସାଦା, ହାଲକା ରଙ୍ଗର ସତହ।",
        guide_lighting_b:"ଆଲୋକ:", guide_lighting:"ସମାନ, ବିସ୍ତାରିତ ଆଲୋକ।",
        guide_same_card_b:"ସମାନ କାର୍ଡ:", guide_same_card:"ସମସ୍ତ ଛଅଟି ଦୃଶ୍ୟରେ ସମାନ କାର୍ଡ ବ୍ୟବହାର କରନ୍ତୁ।",
        left_foot:"ବାମ ପାଦ", right_foot:"ଡାହାଣ ପାଦ",
        view_plantar:"ପ୍ଲାଣ୍ଟାର (ତଳ)", view_dorsal:"ଡୋର୍ସାଲ (ଉପର)", view_medial:"ମିଡିଆଲ (ଭିତର)",
        hint_plantar:"ପାଦ ତଳ", hint_dorsal:"ପାଦ ଉପର", hint_medial:"ଭିତର ପାର୍ଶ୍ୱ",
        settings:"ସେଟିଂସ୍", allow_borrowed_scale:"ଧାର ସ୍କେଲ ଅନୁମତି", lenient_mode:"ଉଦାର ମୋଡ",
        run_inference:"ଅନୁମାନ ଚଲାନ୍ତୁ",
        results:"ଫଳାଫଳ", segmentation_overlay:"ସେଗମେଣ୍ଟେସନ୍ ଓଭରଲେ", predicted_landmarks:"ଅନୁମାନିତ ଲ୍ୟାଣ୍ଡମାର୍କ",
        btn_print_pdf:"PDF ପ୍ରିଣ୍ଟ / ଡାଉନଲୋଡ", btn_download_json:"JSON ଡାଉନଲୋଡ",
        meas_foot_length:"ପାଦ ଲମ୍ବ", meas_forefoot_width:"ଅଗ୍ରପାଦ ଓସାର",
        meas_heel_width:"ଗୋଇଠି ଓସାର", meas_midfoot_width:"ମଧ୍ୟପାଦ ଓସାର",
        meas_toe_axis:"ଆଙ୍ଗୁଠି ଅକ୍ଷ କୋଣ", meas_ball_girth:"ବଲ ପରିଧି", meas_instep_girth:"ଇନଷ୍ଟେପ ପରିଧି",
        meas_malleoli_height:"ମ୍ୟାଲିଓଲାଇ ଉଚ୍ଚତା",
        meas_measurement:"ମାପ", meas_left:"ବାମ", meas_right:"ଡାହାଣ",
        meas_provisional:"ଓସାର ଅନୁପାତ ଉପରେ ଆଧାରିତ ଅସ୍ଥାୟୀ ଅନୁମାନ।",
        // Footwear preparation (technician)
        tech_table_title:"ଜୋତା ପ୍ରସ୍ତୁତି ମୂଲ୍ୟ",
        tech_foot_length_plus2:"ପାଦ ଲମ୍ବ (+2 ସେମି)",
        tech_ball_girth_60pct:"ବଲ ପରିଧି (60%)",
        tech_instep_girth_85pct:"ଇନଷ୍ଟେପ ପରିଧି (85%)",
        tech_malleoli_height:"ମ୍ୟାଲିଓଲାଇ ଉଚ୍ଚତା",
        tech_explainer:"ସଂଯୋଜନ: ପାଦ ଲମ୍ବ +2 ସେମି, ବଲ ପରିଧି ×60%, ଇନଷ୍ଟେପ ପରିଧି ×85%।",
        tech_from_manual:"ମାନୁଆଲ ରୁ",
        meas_estimated_note:"ଗୁଣବତ୍ତା <b>{q}</b>। ଦେଖାଯାଉଥିବା ମାପ ଅନୁମାନ ଏବଂ କମ ସଠିକ ହୋଇପାରେ।",
        meas_estimated_prefix:"ନୋଟ:",
        stage_preprocessing:"ଛବି ପ୍ରିପ୍ରୋସେସ୍ କରୁଛି", stage_segmentation:"ସେଗମେଣ୍ଟ କରୁଛି",
        stage_reference:"ସନ୍ଦର୍ଭ ସ୍କେଲ ଚିହ୍ନଟ କରୁଛି", stage_landmarks:"ଲ୍ୟାଣ୍ଡମାର୍କ ଚିହ୍ନଟ କରୁଛି",
        stage_geometry:"ମାପ ଗଣନା କରୁଛି", stage_complete:"ସମ୍ପୂର୍ଣ୍ଣ",
        status_uploading:"ଅପଲୋଡ ହେଉଛି\u2026", status_running:"ପାଇପଲାଇନ ଚାଲୁଛି\u2026", status_complete:"ଅନୁମାନ ସମ୍ପୂର୍ଣ୍ଣ।",
        inference_history:"ରୋଗୀ ଇତିହାସ", patient_history:"ରୋଗୀ ଇତିହାସ", no_runs_found:"କୌଣସି ରୋଗୀ ରେକର୍ଡ ମିଳିଲା ନାହିଁ।",
        history_loading:"ଲୋଡ ହେଉଛି...", history_failed:"ଇତିହାସ ଲୋଡ ବିଫଳ।",
        language_preference:"ଭାଷା ପସନ୍ଦ", select_language_desc:"ଏପ୍ଲିକେସନ ଇଣ୍ଟରଫେସର ପ୍ରଦର୍ଶନ ଭାଷା ବାଛନ୍ତୁ।",
        help_support:"ସାହାଯ୍ୟ ଏବଂ ସମର୍ଥନ", help_desc:"Lepra 2.0 ବ୍ୟବହାର ବିଷୟରେ ସାଧାରଣ ପ୍ରଶ୍ନର ଉତ୍ତର ଖୋଜନ୍ତୁ।",
        faq_title:"ବାରମ୍ବାର ପଚରାଯାଉଥିବା ପ୍ରଶ୍ନ",
        faq_q1:"ପାଦ ଛବି ସଠିକ ଭାବରେ କିପରି କ୍ୟାପଚର କରିବେ?",
        faq_a1:"ଏକ ମାନକ କ୍ରେଡିଟ/ଡେବିଟ କାର୍ଡ ପାଦ ସହ ସମାନ ସତହରେ ସମତଳ ରଖନ୍ତୁ। କ୍ୟାମେରା ପାଦ ପ୍ରତି ଲମ୍ବବତ ଧରନ୍ତୁ।",
        faq_q2:"'ଧାର ସ୍କେଲ' ର ଅର୍ଥ କଣ?",
        faq_a2:"ଯେତେବେଳେ କୌଣସି ନିର୍ଦ୍ଦିଷ୍ଟ ଦୃଶ୍ୟରେ ସନ୍ଦର୍ଭ କାର୍ଡ ଚିହ୍ନଟ ହୁଏ ନାହିଁ, ସିଷ୍ଟମ ଅନ୍ୟ ଦୃଶ୍ୟରୁ ସ୍କେଲ ଧାର କରେ।",
        faq_q3:"'ବିଶ୍ୱସ୍ତ' ବନାମ 'ନିମ୍ନୀକୃତ' ଗୁଣବତ୍ତା କଣ?",
        faq_a3:'"ବିଶ୍ୱସ୍ତ" ର ଅର୍ଥ ସମସ୍ତ ଦୃଶ୍ୟରେ ଭଲ ସନ୍ଦର୍ଭ କାର୍ଡ ଚିହ୍ନଟ ଥିଲା। "ନିମ୍ନୀକୃତ" ର ଅର୍ଥ କିଛି ଦୃଶ୍ୟରେ ସମସ୍ୟା ଥିଲା।',
        faq_q4:"କିଛି ମାପ ଅସ୍ଥାୟୀ କାହିଁକି ଚିହ୍ନିତ?",
        faq_a4:"ବଲ ପରିଧି ଏବଂ ଇନଷ୍ଟେପ ପରିଧି ଓସାର ଅନୁପାତରୁ ଅନୁମାନ କରାଯାଏ, ତେଣୁ ସେଗୁଡିକ ତାରାଙ୍କ (*) ସହ ଚିହ୍ନିତ।",
        contact_support:"ସମର୍ଥନ ସଂପର୍କ", contact_desc:"ବୈଷୟିକ ସହାୟତା ପାଇଁ, ଦୟାକରି ବିକାଶ ଦଳ ସହ ଯୋଗାଯୋଗ କରନ୍ତୁ।",
        theme_preference:"ଥିମ୍ ପସନ୍ଦ", choose_theme:"ଏପ୍ଲିକେସନ ପାଇଁ ଭିଜୁଆଲ ଥିମ୍ ବାଛନ୍ତୁ।",
        theme_light:"ଲାଇଟ", theme_dark:"ଡାର୍କ",
        sample_image:"ନମୁନା ଛବି", sample_note:"ଉପରେ ଦେଖାଯାଇଥିବା ପରି ସନ୍ଦର୍ଭ କାର୍ଡ ପାଦ ପାଖରେ ରଖନ୍ତୁ।",
        administrator:"ପ୍ରଶାସକ", system_admin:"ସିଷ୍ଟମ ଆଡମିନ", logout:"ଲଗଆଉଟ",
        warn_mask_rejected:"ମାସ୍କ ପ୍ରତ୍ୟାଖ୍ୟାତ", warn_borrowed_scale:"ସନ୍ଦର୍ଭ କାର୍ଡ ମିଳିଲା ନାହିଁ — ଧାର ସ୍କେଲ ବ୍ୟବହାର",
        warn_poor_card:"କାର୍ଡ ଚିହ୍ନଟ ଗୁଣବତ୍ତା ଖରାପ", warn_title:"ଦୃଶ୍ୟ ଗୁଣବତ୍ତା ଚେତାବନୀ",
        full_json_output:"ସମ୍ପୂର୍ଣ୍ଣ JSON ଆଉଟପୁଟ",
        photo_add:"ଫଟୋ ଯୋଡନ୍ତୁ", photo_camera:"ଫଟୋ ନିଅନ୍ତୁ", photo_gallery:"ଗ୍ୟାଲେରୀରୁ ବାଛନ୍ତୁ", photo_cancel:"ବାତିଲ୍"
      },
      te: {
        nav_overview:"అవలోకనం", nav_dashboard:"డాష్‌బోర్డ్", nav_prediction:"కొలత అంచనా",
        nav_history:"రోగి చరిత్ర", nav_settings:"సెట్టింగ్‌లు", nav_language:"భాష",
        nav_help:"సహాయం & మద్దతు", nav_theme:"థీమ్",
        stat_total_predictions:"మొత్తం అంచనాలు", stat_successful_runs:"పూర్తయిన అంచనాలు",
        stat_last_run:"చివరి రన్",
        recent_predictions:"ఇటీవలి అంచనాలు",
        no_predictions_yet:"ఇంకా అంచనాలు లేవు. మీ మొదటి అనుమానాన్ని అమలు చేయడానికి మోడల్ అంచనాకు వెళ్ళండి.",
        th_patient:"రోగి", th_date:"తేదీ", th_foot_length_lr:"పాద పొడవు (ఎ/కు)",
        th_run_id:"రన్ ID", th_actions:"చర్యలు",
        patient_information:"ఆరోగ్య సేవలు పొందువారి వివరాలు",
        lbl_patient_id:"ఆరోగ్య సేవలు పొందువారి ఐడి", lbl_patient_name:"ఆరోగ్య సేవలు పొందువారి పేరు", lbl_age:"వయసు", lbl_gender:"లింగం",
        lbl_abha_id:"ABHA ID", lbl_aadhar_id:"Aadhar Number", lbl_diabetes:"డయాబెటిస్ ఉందా?", lbl_amputated_toes:"కాలి వేళ్లు తొలగించబడ్డాయి",
        lbl_disease_type:"వ్యాధి రకం", opt_leprosy:"కుష్ఠు వ్యాధి", opt_lf:"లింఫాటిక్ ఫైలేరియాసిస్ (LF)",
        lbl_who_grade:"WHO Disability Grade", opt_grade_none:"None", opt_grade_1:"Grade 1", opt_grade_2:"Grade 2", opt_grade_3:"Grade 3", opt_grade_4:"Grade 4",
        lbl_exam_date:"కొలిచిన తేదీ", lbl_capture_center:"కేంద్రం పేరు", lbl_referring_doctor:"రిఫర్ చేసిన వైద్యుడు",
        lbl_district:"District", lbl_village:"Village", lbl_captured_by:"Captured By", opt_other_staff:"Other (not in list)",
        lbl_clinical_notes:"అదనపు గమనికలు/వ్యాఖ్యలు", lbl_phone:"Phone Number",
        ph_full_name:"ఉదా., రమేష్ కుమార్", ph_years:"ఉదా., 45", ph_hospital:"ఆసుపత్రి / క్లినిక్ పేరు", ph_phone:"+91 XXXXX XXXXX", ph_aadhar:"XXXX XXXX XXXX", ph_village:"Village name",
        manual_measurements:"Manual Measurements (Optional)", manual_measurements_desc:"Enter tape-measured values for comparison with AI estimates. All values in cm.",
        ph_clinical_notes:"ఏదైనా ప్రత్యేక స్థితి, పరిశీలనలు లేదా అభ్యర్థనలు...",
        opt_select:"ఎంచుకోండి", opt_male:"పురుషుడు", opt_female:"స్త్రీ", opt_other:"ఇతర",
        opt_yes:"అవును", opt_no:"కాదు",
        foot_images:"పాదాల ఫోటోలు", image_guidelines:"చిత్ర క్యాప్చర్ మార్గదర్శకాలు",
        guide_ref_card_b:"రిఫరెన్స్ కార్డ్:", guide_ref_card:"ఒక ప్రామాణిక క్రెడిట్/డెబిట్ కార్డ్‌ని పాదం ఉన్న అదే ఉపరితలంపై చదునుగా ఉంచండి.",
        guide_camera_b:"కెమెరా కోణం:", guide_camera:"కెమెరాను లంబంగా పట్టుకోండి.",
        guide_framing_b:"ఫ్రేమింగ్:", guide_framing:"పాదం మరియు కార్డ్ మాత్రమే కనిపించాలి.",
        guide_background_b:"నేపథ్యం:", guide_background:"సాదా, తేలికపాటి రంగు ఉపరితలం.",
        guide_lighting_b:"లైటింగ్:", guide_lighting:"సమానమైన, వ్యాపించిన వెలుతురు.",
        guide_same_card_b:"అదే కార్డ్:", guide_same_card:"అన్ని ఆరు వ్యూలలో అదే కార్డ్ ఉపయోగించండి.",
        left_foot:"ఎడమ పాదం", right_foot:"కుడి పాదం",
        view_plantar:"ప్లాంటార్ (అరికాలు)", view_dorsal:"డోర్సల్ (పైభాగం)", view_medial:"మీడియల్ (లోపలి)",
        hint_plantar:"పాద అడుగు", hint_dorsal:"పాద పైభాగం", hint_medial:"లోపలి వైపు",
        settings:"సెట్టింగ్‌లు", allow_borrowed_scale:"అరువు స్కేల్ అనుమతించు", lenient_mode:"సరళ మోడ్",
        run_inference:"కొలతలను అంచనా వేయండి",
        results:"ఫలితాలు", segmentation_overlay:"సెగ్మెంటేషన్ ఓవర్‌లే", predicted_landmarks:"అంచనా వేసిన ల్యాండ్‌మార్క్‌లు",
        btn_print_pdf:"PDF ప్రింట్ / డౌన్‌లోడ్", btn_download_json:"JSON డౌన్‌లోడ్",
        meas_foot_length:"పాద పొడవు", meas_forefoot_width:"ముందు పాద వెడల్పు",
        meas_heel_width:"మడమ వెడల్పు", meas_midfoot_width:"మధ్య పాద వెడల్పు",
        meas_toe_axis:"కాలి వేలు అక్షం కోణం", meas_ball_girth:"బాల్ గర్త్", meas_instep_girth:"ఇన్‌స్టెప్ గర్త్",
        meas_malleoli_height:"మాలియోలై ఎత్తు",
        // Footwear preparation (technician)
        tech_table_title:"పాదరక్షల తయారీ విలువలు",
        tech_foot_length_plus2:"పాద పొడవు (+2 సెం.మీ)",
        tech_ball_girth_60pct:"బాల్ గర్త్ (60%)",
        tech_instep_girth_85pct:"ఇన్‌స్టెప్ గర్త్ (85%)",
        tech_malleoli_height:"మాలియోలై ఎత్తు",
        tech_explainer:"సర్దుబాట్లు: పాద పొడవు +2 సెం.మీ, బాల్ గర్త్ ×60%, ఇన్‌స్టెప్ గర్త్ ×85%.",
        tech_from_manual:"మాన్యువల్ నుండి",
        meas_measurement:"కొలత", meas_left:"ఎడమ", meas_right:"కుడి",
        meas_provisional:"వెడల్పు నిష్పత్తుల ఆధారంగా తాత్కాలిక అంచనాలు.",
        meas_estimated_note:"నాణ్యత <b>{q}</b>. చూపిన కొలతలు అంచనాలు మరియు తక్కువ ఖచ్చితమైనవి కావచ్చు.",
        meas_estimated_prefix:"గమనిక:",
        stage_preprocessing:"చిత్రాలను ప్రీప్రాసెస్ చేస్తోంది", stage_segmentation:"విభజిస్తోంది",
        stage_reference:"రిఫరెన్స్ స్కేల్ గుర్తిస్తోంది", stage_landmarks:"ల్యాండ్‌మార్క్‌లు గుర్తిస్తోంది",
        stage_geometry:"కొలతలు గణిస్తోంది", stage_complete:"పూర్తయింది",
        status_uploading:"అప్‌లోడ్ అవుతోంది\u2026", status_running:"ప్రాసెస్ అవుతోంది...", status_complete:"అనుమానం పూర్తయింది.",
        inference_history:"రోగి చరిత్ర", patient_history:"రోగి చరిత్ర", no_runs_found:"రోగి రికార్డులు కనుగొనబడలేదు.",
        history_loading:"లోడ్ అవుతోంది...", history_failed:"చరిత్ర లోడ్ విఫలమైంది.",
        language_preference:"భాష ప్రాధాన్యత", select_language_desc:"అప్లికేషన్ ఇంటర్‌ఫేస్ ప్రదర్శన భాషను ఎంచుకోండి.",
        help_support:"సహాయం & మద్దతు", help_desc:"Lepra 2.0 ఉపయోగించడం గురించి సాధారణ ప్రశ్నలకు సమాధానాలు కనుగొనండి.",
        faq_title:"తరచుగా అడిగే ప్రశ్నలు",
        faq_q1:"పాద చిత్రాలను సరిగ్గా ఎలా తీయాలి?",
        faq_a1:"ఒక ప్రామాణిక క్రెడిట్/డెబిట్ కార్డ్‌ని పాదం ఉన్న అదే ఉపరితలంపై చదునుగా ఉంచండి. కెమెరాను లంబంగా పట్టుకోండి.",
        faq_q2:'"అరువు స్కేల్" అంటే ఏమిటి?',
        faq_a2:"రిఫరెన్స్ కార్డ్ కనుగొనబడనప్పుడు, సిస్టమ్ అదే పాదం యొక్క మరొక వ్యూ నుండి స్కేల్ అరువు తీసుకుంటుంది.",
        faq_q3:'"విశ్వసనీయం" vs "తగ్గినది" నాణ్యత ఏమిటి?',
        faq_a3:'"విశ్వసనీయం" అంటే అన్ని వ్యూలలో మంచి రిఫరెన్స్ కార్డ్ గుర్తింపు ఉంది. "తగ్గినది" అంటే కొన్ని వ్యూలలో సమస్యలు ఉన్నాయి.',
        faq_q4:"కొన్ని కొలతలు తాత్కాలికం అని ఎందుకు గుర్తించబడ్డాయి?",
        faq_a4:"బాల్ చుట్టుకొలత మరియు ఇన్‌స్టెప్ చుట్టుకొలత వెడల్పు నిష్పత్తుల నుండి అంచనా వేయబడతాయి.",
        contact_support:"మద్దతు సంప్రదించండి", contact_desc:"సాంకేతిక సహాయం కోసం, దయచేసి అభివృద్ధి బృందాన్ని సంప్రదించండి.",
        theme_preference:"థీమ్ ప్రాధాన్యత", choose_theme:"అప్లికేషన్ కోసం దృశ్య థీమ్ ఎంచుకోండి.",
        theme_light:"లైట్", theme_dark:"డార్క్",
        sample_image:"నమూనా చిత్రం", sample_note:"పైన చూపిన విధంగా రిఫరెన్స్ కార్డ్‌ని పాదం దగ్గర ఉంచండి.",
        administrator:"నిర్వాహకుడు", system_admin:"సిస్టమ్ అడ్మిన్", logout:"లాగ్ అవుట్",
        warn_mask_rejected:"మాస్క్ తిరస్కరించబడింది", warn_borrowed_scale:"రిఫరెన్స్ కార్డ్ కనుగొనబడలేదు — అరువు స్కేల్ ఉపయోగం",
        warn_poor_card:"కార్డ్ గుర్తింపు నాణ్యత తక్కువ", warn_title:"వ్యూ నాణ్యత హెచ్చరికలు",
        full_json_output:"పూర్తి JSON అవుట్‌పుట్",
        photo_add:"ఫోటో జోడించండి", photo_camera:"ఫోటో తీయండి", photo_gallery:"గ్యాలరీ నుండి ఎంచుకోండి", photo_cancel:"రద్దు చేయండి"
      },
      mr: {
        nav_overview:"आढावा", nav_dashboard:"डॅशबोर्ड", nav_prediction:"मोजमाप अंदाज",
        nav_history:"रुग्ण इतिहास", nav_settings:"सेटिंग्ज", nav_language:"भाषा",
        nav_help:"मदत आणि समर्थन", nav_theme:"थीम",
        stat_total_predictions:"एकूण अंदाज", stat_successful_runs:"पूर्ण अंदाज",
        stat_last_run:"शेवटचा रन",
        recent_predictions:"अलीकडील अंदाज",
        no_predictions_yet:"अद्याप कोणतेही अंदाज नाहीत. तुमचा पहिला अनुमान चालवण्यासाठी मॉडेल अंदाजावर जा.",
        th_patient:"रुग्ण", th_date:"तारीख", th_foot_length_lr:"पायाची लांबी (डा/उ)",
        th_run_id:"रन ID", th_actions:"कृती",
        patient_information:"रुग्ण माहिती",
        lbl_patient_id:"रुग्ण ID", lbl_patient_name:"रुग्णाचे नाव", lbl_age:"वय", lbl_gender:"लिंग",
        lbl_abha_id:"ABHA ID", lbl_aadhar_id:"Aadhar Number", lbl_diabetes:"मधुमेह", lbl_amputated_toes:"कापलेली बोटे",
        lbl_disease_type:"रोगाचा प्रकार", opt_leprosy:"कुष्ठरोग", opt_lf:"लिम्फॅटिक फायलेरियासिस (LF)",
        lbl_who_grade:"WHO Disability Grade", opt_grade_none:"None", opt_grade_1:"Grade 1", opt_grade_2:"Grade 2", opt_grade_3:"Grade 3", opt_grade_4:"Grade 4",
        lbl_exam_date:"तपासणी तारीख", lbl_capture_center:"कॅप्चर केंद्र", lbl_referring_doctor:"संदर्भ देणारे डॉक्टर",
        lbl_district:"District", lbl_village:"Village", lbl_captured_by:"Captured By", opt_other_staff:"Other (not in list)",
        lbl_clinical_notes:"नैदानिक नोट्स", lbl_phone:"Phone Number",
        ph_full_name:"पूर्ण नाव", ph_years:"वर्षे", ph_hospital:"रुग्णालय / क्लिनिक नाव", ph_phone:"+91 XXXXX XXXXX", ph_aadhar:"XXXX XXXX XXXX", ph_village:"Village name",
        manual_measurements:"Manual Measurements (Optional)", manual_measurements_desc:"Enter tape-measured values for comparison with AI estimates. All values in cm.",
        ph_clinical_notes:"कोणताही संबंधित इतिहास, विकृती, लक्षणे...",
        opt_select:"निवडा", opt_male:"पुरुष", opt_female:"स्त्री", opt_other:"इतर",
        opt_yes:"हो", opt_no:"नाही",
        foot_images:"पायाचे फोटो", image_guidelines:"प्रतिमा कॅप्चर मार्गदर्शक तत्त्वे",
        guide_ref_card_b:"संदर्भ कार्ड:", guide_ref_card:"एक मानक क्रेडिट/डेबिट कार्ड पायाच्या समान पृष्ठभागावर सपाट ठेवा.",
        guide_camera_b:"कॅमेरा कोन:", guide_camera:"कॅमेरा लंबवत धरा.",
        guide_framing_b:"फ्रेमिंग:", guide_framing:"फक्त पाय आणि कार्ड दिसले पाहिजे.",
        guide_background_b:"पार्श्वभूमी:", guide_background:"साधा, हलक्या रंगाचा पृष्ठभाग.",
        guide_lighting_b:"प्रकाश:", guide_lighting:"समान, विखुरलेला प्रकाश.",
        guide_same_card_b:"एकच कार्ड:", guide_same_card:"सर्व सहा दृश्यांमध्ये एकच कार्ड वापरा.",
        left_foot:"डावा पाय", right_foot:"उजवा पाय",
        view_plantar:"प्लांटार (तळवा)", view_dorsal:"डोर्सल (वरचा)", view_medial:"मीडियल (आतील)",
        hint_plantar:"पायाचा तळ", hint_dorsal:"पायाचा वरचा भाग", hint_medial:"आतील बाजू",
        settings:"सेटिंग्ज", allow_borrowed_scale:"उधार स्केल अनुमती", lenient_mode:"सौम्य मोड",
        run_inference:"अनुमान चालवा",
        results:"निकाल", segmentation_overlay:"सेगमेंटेशन ओव्हरले", predicted_landmarks:"अनुमानित लँडमार्क",
        btn_print_pdf:"PDF प्रिंट / डाउनलोड", btn_download_json:"JSON डाउनलोड",
        meas_foot_length:"पायाची लांबी", meas_forefoot_width:"पुढचा पाय रुंदी",
        meas_heel_width:"टाच रुंदी", meas_midfoot_width:"मध्य पाय रुंदी",
        meas_toe_axis:"बोट अक्ष कोन", meas_ball_girth:"बॉल परिघ", meas_instep_girth:"इन्स्टेप परिघ",
        meas_malleoli_height:"मॅलिओलाई उंची",
        // Footwear preparation (technician)
        tech_table_title:"पादत्राण तयारी मूल्ये",
        tech_foot_length_plus2:"पाय लांबी (+2 सेमी)",
        tech_ball_girth_60pct:"बॉल परिघ (60%)",
        tech_instep_girth_85pct:"इन्स्टेप परिघ (85%)",
        tech_malleoli_height:"मॅलिओलाई उंची",
        tech_explainer:"समायोजन: पाय लांबी +2 सेमी, बॉल परिघ ×60%, इन्स्टेप परिघ ×85%.",
        tech_from_manual:"मॅन्युअल वरून",
        meas_measurement:"मोजमाप", meas_left:"डावा", meas_right:"उजवा",
        meas_provisional:"रुंदी गुणोत्तरावर आधारित तात्पुरते अंदाज.",
        meas_estimated_note:"गुणवत्ता <b>{q}</b> आहे. दर्शवलेली मोजमापे अंदाज आहेत आणि कमी अचूक असू शकतात.",
        meas_estimated_prefix:"टीप:",
        stage_preprocessing:"प्रतिमा प्रीप्रोसेस करत आहे", stage_segmentation:"विभागणी करत आहे",
        stage_reference:"संदर्भ स्केल शोधत आहे", stage_landmarks:"लँडमार्क शोधत आहे",
        stage_geometry:"मोजमाप गणना करत आहे", stage_complete:"पूर्ण",
        status_uploading:"अपलोड होत आहे\u2026", status_running:"पाइपलाइन चालू आहे\u2026", status_complete:"अनुमान पूर्ण.",
        inference_history:"रुग्ण इतिहास", patient_history:"रुग्ण इतिहास", no_runs_found:"कोणतेही रुग्ण नोंदी सापडल्या नाहीत.",
        history_loading:"लोड होत आहे...", history_failed:"इतिहास लोड अयशस्वी.",
        language_preference:"भाषा प्राधान्य", select_language_desc:"अनुप्रयोग इंटरफेसची प्रदर्शन भाषा निवडा.",
        help_support:"मदत आणि समर्थन", help_desc:"Lepra 2.0 वापरण्याबद्दल सामान्य प्रश्नांची उत्तरे शोधा.",
        faq_title:"वारंवार विचारले जाणारे प्रश्न",
        faq_q1:"पायाचे फोटो योग्यरित्या कसे काढावेत?",
        faq_a1:"एक मानक क्रेडिट/डेबिट कार्ड पायाच्या समान पृष्ठभागावर सपाट ठेवा. कॅमेरा लंबवत धरा.",
        faq_q2:'"उधार स्केल" म्हणजे काय?',
        faq_a2:"जेव्हा संदर्भ कार्ड सापडत नाही, तेव्हा सिस्टम त्याच पायाच्या दुसऱ्या दृश्यातून स्केल उधार घेते.",
        faq_q3:'"विश्वसनीय" विरुद्ध "निम्नीकृत" गुणवत्ता काय आहे?',
        faq_a3:'"विश्वसनीय" म्हणजे सर्व दृश्यांमध्ये चांगली संदर्भ कार्ड ओळख होती. "निम्नीकृत" म्हणजे काही दृश्यांमध्ये समस्या होत्या.',
        faq_q4:"काही मोजमापे तात्पुरती म्हणून का चिन्हांकित आहेत?",
        faq_a4:"बॉल परिघ आणि इन्स्टेप परिघ रुंदी गुणोत्तरांवरून अंदाज लावले जातात, म्हणून ते तारांकन (*) सह चिन्हांकित आहेत.",
        contact_support:"समर्थन संपर्क", contact_desc:"तांत्रिक सहाय्यासाठी, कृपया विकास संघाशी संपर्क साधा.",
        theme_preference:"थीम प्राधान्य", choose_theme:"अनुप्रयोगासाठी दृश्य थीम निवडा.",
        theme_light:"लाइट", theme_dark:"डार्क",
        sample_image:"नमुना प्रतिमा", sample_note:"वरील दर्शवल्याप्रमाणे संदर्भ कार्ड पायाजवळ ठेवा.",
        administrator:"प्रशासक", system_admin:"सिस्टम अ‍ॅडमिन", logout:"लॉगआउट",
        warn_mask_rejected:"मास्क नाकारला", warn_borrowed_scale:"संदर्भ कार्ड सापडले नाही — उधार स्केल वापर",
        warn_poor_card:"कार्ड ओळख गुणवत्ता खराब", warn_title:"दृश्य गुणवत्ता इशारे",
        full_json_output:"पूर्ण JSON आउटपुट",
        photo_add:"फोटो जोडा", photo_camera:"फोटो काढा", photo_gallery:"गॅलरीमधून निवडा", photo_cancel:"रद्द करा"
      }
    };

    let _currentLang = 'en';
    function T(key) {
      return (TRANSLATIONS[_currentLang] && TRANSLATIONS[_currentLang][key]) || TRANSLATIONS.en[key] || key;
    }
    function setLanguage(lang) {
      _currentLang = lang;
      // Translate static elements
      document.querySelectorAll('[data-i18n]').forEach(el => {
        const k = el.getAttribute('data-i18n');
        const t = T(k);
        if (t) el.textContent = t;
      });
      // Translate placeholders
      document.querySelectorAll('[data-i18n-ph]').forEach(el => {
        const k = el.getAttribute('data-i18n-ph');
        const t = T(k);
        if (t) el.placeholder = t;
      });
      // Update page title
      const hash = (location.hash || '#dashboard').slice(1);
      const titleKey = PAGE_TITLE_KEYS[hash];
      if (titleKey) document.getElementById('page-title').textContent = T(titleKey);
      // Persist
      localStorage.setItem('lepra-lang', lang);
      const sel = document.getElementById('lang-select');
      if (sel) sel.value = lang;
      // Reload dynamic content
      dashboardLoaded = false;
      historyLoaded = false;
      const active = (location.hash || '#dashboard').slice(1);
      if (active === 'dashboard') loadDashboard();
      if (active === 'history') loadHistory();
    }

    // ── Router ──
    const SECTIONS = ['dashboard','prediction','history','agents','language','about','help','theme'];
    const PAGE_TITLE_KEYS = {
      dashboard: 'nav_dashboard',
      prediction: 'nav_prediction',
      history: 'patient_history',
      agents: 'nav_agents',
      language: 'language_preference',
      about: 'nav_about',
      help: 'nav_help',
      theme: 'nav_theme'
    };
    const PAGE_TITLES = {
      dashboard: 'Dashboard',
      prediction: 'Model Prediction',
      history: 'Patient History',
      agents: 'Agent Management',
      language: 'Language Preference',
      about: 'About Us',
      help: 'Help & Support',
      theme: 'Theme'
    };

    // ── Current user info ──
    let _userRole = 'admin';
    let _userName = 'Admin';
    async function initUserProfile() {
      try {
        const r = await fetch('/api/me');
        if (r.ok) {
          const d = await r.json();
          _userRole = d.role || 'admin';
          _userName = d.name || d.username || 'User';
          document.getElementById('profile-avatar').textContent = _userName.charAt(0).toUpperCase();
          document.getElementById('profile-name-display').textContent = _userName;
          document.getElementById('pd-name-display').textContent = _userName;
          document.getElementById('pd-role-display').textContent = _userRole === 'admin' ? 'Administrator' : 'Field Agent';
          // Hide admin-only items for agents
          document.querySelectorAll('.admin-only').forEach(el => {
            el.style.display = _userRole === 'admin' ? '' : 'none';
          });
        }
      } catch(e) { console.warn('initUserProfile error:', e); }
    }
    initUserProfile();

    function router() {
      const hash = (location.hash || '#dashboard').slice(1);
      const active = SECTIONS.includes(hash) ? hash : 'dashboard';
      // Block agents from admin-only sections
      if (active === 'agents' && _userRole !== 'admin') {
        location.hash = '#dashboard';
        return;
      }
      SECTIONS.forEach(s => {
        const el = document.getElementById('sec-' + s);
        if (el) {
          el.classList.toggle('active', s === active);
        }
      });
      document.querySelectorAll('.sidebar-item').forEach(el => {
        el.classList.toggle('active', el.dataset.section === active);
      });
      const titleKey = PAGE_TITLE_KEYS[active];
      document.getElementById('page-title').textContent = titleKey ? T(titleKey) : (PAGE_TITLES[active] || active);
      if (active === 'dashboard') loadDashboard();
      if (active === 'history') loadHistory();
      if (active === 'agents') loadAgents();
    }
    window.addEventListener('hashchange', router);

    // ── Sidebar toggle ──
    document.getElementById('sidebar-toggle').addEventListener('click', () => {
      if (window.innerWidth <= 767) {
        document.body.classList.toggle('sidebar-expanded');
      } else {
        document.body.classList.toggle('sidebar-collapsed');
      }
    });
    // Mobile topbar hamburger
    document.getElementById('mob-menu-btn').addEventListener('click', () => {
      document.body.classList.toggle('sidebar-expanded');
    });
    // Backdrop tap closes sidebar
    document.getElementById('sidebar-backdrop').addEventListener('click', () => {
      document.body.classList.remove('sidebar-expanded');
    });
    // Close mobile sidebar on nav click
    document.querySelectorAll('.sidebar-item').forEach(el => {
      el.addEventListener('click', () => {
        if (window.innerWidth <= 767) {
          document.body.classList.remove('sidebar-expanded');
        }
      });
    });

    // ── Profile dropdown ──
    const profileBtn = document.getElementById('profile-btn');
    const profileDD = document.getElementById('profile-dropdown');
    profileBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      profileDD.classList.toggle('open');
    });
    document.addEventListener('click', () => { profileDD.classList.remove('open'); });

    document.getElementById('logout-btn').addEventListener('click', async () => {
      await fetch('/api/logout', { method: 'POST' });
      window.location.reload();
    });

    // ── Theme ──
    function setTheme(t) {
      document.documentElement.setAttribute('data-theme', t);
      document.getElementById('theme-light').classList.toggle('active', t === 'light');
      document.getElementById('theme-dark').classList.toggle('active', t === 'dark');
      localStorage.setItem('lepra-theme', t);
    }
    // Restore saved theme
    (function() {
      const saved = localStorage.getItem('lepra-theme');
      if (saved === 'dark') setTheme('dark');
    })();

    // ── Dashboard loading ──
    let dashboardLoaded = false;
    async function loadDashboard() {
      if (dashboardLoaded) return;
      try {
        const r = await fetch('/api/stats');
        if (!r.ok) return;
        const d = await r.json();
        document.getElementById('stat-total').textContent = d.total || 0;
        document.getElementById('stat-success').textContent = d.successful || 0;
        document.getElementById('stat-recent').textContent = d.recent_date || '--';
        const avgEl = document.getElementById('stat-avgtime');
        if (avgEl) {
          if (d.avg_inference_secs != null) {
            const secs = d.avg_inference_secs;
            avgEl.textContent = secs >= 60 ? Math.floor(secs/60) + 'm ' + Math.round(secs%60) + 's' : secs + 's';
          } else {
            avgEl.textContent = '--';
          }
        }
        dashboardLoaded = true;

        // Recent runs
        const h = await fetch('/api/history');
        if (!h.ok) return;
        const runs = await h.json();
        const container = document.getElementById('recent-runs');
        if (runs.length === 0) {
          container.innerHTML = '<div class="history-empty">' + T('no_predictions_yet') + '</div>';
        } else {
          const recent = runs.slice(0, 5);
          let html = '<table class="meas-table"><thead><tr><th>' + T('th_patient') + '</th><th>' + T('th_date') + '</th><th>' + T('th_foot_length_lr') + '</th></tr></thead><tbody>';
          for (const run of recent) {
            html += '<tr>';
            html += '<td>' + (run.patient_name || run.patient_id) + '</td>';
            html += '<td>' + (run.date || '--') + '</td>';
            html += '<td class="num">' + (run.foot_length_left || '--') + ' / ' + (run.foot_length_right || '--') + '</td>';
            html += '</tr>';
          }
          html += '</tbody></table>';
          container.innerHTML = html;
        }

        // Charts (admin only — endpoint returns 403 for agents)
        _loadDashboardCharts();
      } catch(e) { console.warn('loadDashboard error:', e); }
    }

    // Chart.js instances + raw dashboard data for date filtering
    const _charts = {};
    let _dashData = null;

    function filterDashboard() {
      if (!_dashData) return;
      const from = (document.getElementById('dash-date-from') || {}).value || '';
      const to   = (document.getElementById('dash-date-to') || {}).value || '';
      const byMonth = {};
      for (const [k, v] of Object.entries(_dashData.by_month || {})) {
        if (from && k < from.slice(0,7)) continue;
        if (to   && k > to.slice(0,7))   continue;
        byMonth[k] = v;
      }
      _renderCharts({ ..._dashData, by_month: byMonth });
    }

    function clearDashboardDates() {
      const f = document.getElementById('dash-date-from');
      const t = document.getElementById('dash-date-to');
      if (f) f.value = '';
      if (t) t.value = '';
      if (_dashData) _renderCharts(_dashData);
    }

    function _renderCharts(d) {
      const ACCENT = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#2563eb';
      const COLORS = ['#2563eb','#7c3aed','#f59e0b','#ef4444','#10b981','#3b82f6','#ec4899','#6366f1'];

      function _mkChart(id, type, labels, data, bgColors) {
        if (_charts[id]) _charts[id].destroy();
        const el2 = document.getElementById(id); const ctx = el2 ? el2.getContext('2d') : null;
        if (!ctx) return;
        _charts[id] = new Chart(ctx, {
          type,
          data: { labels, datasets: [{ data, backgroundColor: bgColors || COLORS, borderColor: type === 'line' ? ACCENT : undefined, borderWidth: type === 'line' ? 2 : 1, fill: type === 'line', tension: 0.3 }] },
          options: { responsive: true, plugins: { legend: { display: type !== 'line' && type !== 'bar' } }, scales: (type === 'line' || type === 'bar') ? { y: { beginAtZero: true } } : {} }
        });
      }

      const months = Object.keys(d.by_month || {}).sort();
      _mkChart('chart-by-month', 'line', months, months.map(m => d.by_month[m]), null);

      const centers = Object.keys(d.by_center || {});
      _mkChart('chart-by-center', 'bar', centers, centers.map(c => d.by_center[c]), COLORS.slice(0, centers.length));

      const gKeys = Object.keys(d.by_gender || {});
      _mkChart('chart-by-gender', 'doughnut', gKeys, gKeys.map(k => d.by_gender[k]), ['#3b82f6','#ec4899','#6366f1']);
    }

    async function _loadDashboardCharts() {
      // Charts are admin-only — skip the request entirely for agents
      if (_userRole !== 'admin') return;
      try {
        const r = await fetch('/api/dashboard');
        if (!r.ok) return;
        _dashData = await r.json();
        document.getElementById('charts-grid').style.display = '';
        _renderCharts(_dashData);
      } catch(e) { console.warn('charts error:', e); }
      _loadDrilldown();
    }

    // ── State -> District -> User drill-down ──
    let _ddData = null;             // raw {summary, tree, users} from the API
    let _ddPath = [];                // e.g. [] | ["Andhra Pradesh"] | ["Andhra Pradesh", "Guntur"]
    let _canonicalStates = null;    // full state list from /api/centers (districts.csv), cached

    async function _getCanonicalStates() {
      if (_canonicalStates) return _canonicalStates;
      try {
        const r = await fetch('/api/centers');
        if (!r.ok) return [];
        const data = await r.json();
        _canonicalStates = data.states || [];
      } catch(e) {
        console.warn('canonical states fetch error:', e);
        _canonicalStates = [];
      }
      return _canonicalStates;
    }

    async function _loadDrilldown() {
      if (_userRole !== 'admin') return;
      try {
        const from = (document.getElementById('dd-date-from') || {}).value || '';
        const to   = (document.getElementById('dd-date-to')   || {}).value || '';
        const qs = new URLSearchParams();
        if (from) qs.set('date_from', from);
        if (to)   qs.set('date_to', to);
        const r = await fetch('/api/dashboard/drilldown?' + qs.toString());
        if (!r.ok) return;
        _ddData = await r.json();
        document.getElementById('drilldown-grid').style.display = '';
        // Note: #dd-user-filter is intentionally NOT populated here from a
        // flat _ddData.users list — it is scoped to the selected state +
        // district and populated/disabled inside _setDrilldownPath() below,
        // so it can never show a user tied to a different state/district.
        // State dropdown lists every canonical state configured in the app
        // (from /api/centers, sourced from districts.csv) — not just states
        // that happen to already have submitted patient runs in _ddData.tree.
        const states = await _getCanonicalStates();
        const stateSel = document.getElementById('dd-state-filter');
        if (stateSel) {
          const current = stateSel.value;
          stateSel.innerHTML = '<option value="">All States</option>';
          states.slice().sort().forEach(function(s) {
            const o = document.createElement('option');
            o.value = s; o.textContent = s;
            stateSel.appendChild(o);
          });
          // Patients submitted without a state tag (e.g. captured before the
          // State field existed, or left blank) are bucketed server-side
          // under "Unknown" — surface that bucket explicitly so those
          // records are reachable instead of silently invisible.
          const unknownBucket = ((_ddData.tree || {})['Unknown'] || {});
          if ((unknownBucket.count || 0) > 0) {
            const o = document.createElement('option');
            o.value = 'Unknown'; o.textContent = 'Unassigned / No State Recorded';
            stateSel.appendChild(o);
          }
          stateSel.value = current;
        }
        _setDrilldownPath([]);
      } catch(e) { console.warn('drilldown error:', e); }
    }

    function reloadDrilldown() {
      _loadDrilldown();
    }

    function clearDrilldownDates() {
      const f = document.getElementById('dd-date-from');
      const t = document.getElementById('dd-date-to');
      if (f) f.value = '';
      if (t) t.value = '';
      _loadDrilldown();
    }

    // Single shared entry point for every way the drill-down path can change
    // (breadcrumb clicks, chart-bar clicks, state/district dropdowns) so all
    // of them stay in sync with each other.
    function _setDrilldownPath(path) {
      _ddPath = path || [];
      const stateSel = document.getElementById('dd-state-filter');
      const districtSel = document.getElementById('dd-district-filter');
      const state = _ddPath[0] || '';
      const district = _ddPath[1] || '';

      if (stateSel) stateSel.value = state;

      if (districtSel) {
        if (!state) {
          districtSel.disabled = true;
          districtSel.innerHTML = '<option value="">Select a state first</option>';
        } else if (_ddData && _ddData.tree && _ddData.tree[state]) {
          districtSel.disabled = false;
          districtSel.innerHTML = '<option value="">All Districts</option>';
          Object.keys((_ddData.tree[state] || {}).districts || {}).sort().forEach(function(d) {
            const o = document.createElement('option');
            o.value = d; o.textContent = d;
            districtSel.appendChild(o);
          });
          districtSel.value = district;
        } else {
          // Canonical state with zero submitted patients in the current
          // (possibly date-filtered) window. Left enabled (not hard-disabled)
          // so the dropdown never feels stuck — the state selector above it
          // remains the primary way to move on to a different state.
          districtSel.disabled = false;
          districtSel.innerHTML = '<option value="">No districts yet for this state</option>';
        }
      }

      // User dropdown is scoped to the currently selected state + district —
      // never a flat global list — so it can never show a user tied to a
      // different state/district than the one being viewed.
      const userSel = document.getElementById('dd-user-filter');
      if (userSel) {
        const currentUser = userSel.value;
        if (!state) {
          userSel.disabled = true;
          userSel.innerHTML = '<option value="">Select a state first</option>';
        } else if (!district) {
          userSel.disabled = true;
          userSel.innerHTML = '<option value="">Select a district first</option>';
        } else {
          const districtData = ((_ddData && _ddData.tree && _ddData.tree[state] || {}).districts || {})[district];
          const users = (districtData || {}).users || {};
          const userNames = Object.keys(users).sort();
          if (userNames.length) {
            userSel.disabled = false;
            userSel.innerHTML = '<option value="">All Users</option>';
            userNames.forEach(function(u) {
              const o = document.createElement('option');
              o.value = u; o.textContent = u;
              userSel.appendChild(o);
            });
            userSel.value = userNames.includes(currentUser) ? currentUser : '';
          } else {
            userSel.disabled = false;
            userSel.innerHTML = '<option value="">No users yet for this district</option>';
          }
        }
      }

      _renderDrilldownLevel();
    }

    function _onStateFilterChange() {
      const state = document.getElementById('dd-state-filter').value;
      _setDrilldownPath(state ? [state] : []);
    }

    function _onDistrictFilterChange() {
      const state = document.getElementById('dd-state-filter').value;
      const district = document.getElementById('dd-district-filter').value;
      _setDrilldownPath(district ? [state, district] : [state]);
    }

    function _drilldownGoTo(depth) {
      _setDrilldownPath(_ddPath.slice(0, depth));
    }

    function _renderDrilldownBreadcrumb() {
      const el = document.getElementById('dd-breadcrumb');
      if (!el) return;
      let html = '<span onclick="_drilldownGoTo(0)" style="cursor:pointer;text-decoration:underline;">All States</span>';
      _ddPath.forEach(function(label, i) {
        html += ' &rsaquo; <span onclick="_drilldownGoTo(' + (i + 1) + ')" style="cursor:' + (i < _ddPath.length - 1 ? 'pointer' : 'default') + ';text-decoration:' + (i < _ddPath.length - 1 ? 'underline' : 'none') + ';">' + label + '</span>';
      });
      el.innerHTML = html;
    }

    function _userFilteredCount(usersDict, userFilter) {
      if (!userFilter) {
        return Object.values(usersDict || {}).reduce(function(a, b) { return a + b; }, 0);
      }
      return (usersDict || {})[userFilter] || 0;
    }

    function _renderDrilldownLevel() {
      if (!_ddData) return;
      _renderDrilldownBreadcrumb();
      const userFilter = (document.getElementById('dd-user-filter') || {}).value || '';
      const tree = _ddData.tree || {};
      let labels = [];
      let values = [];
      let onClick = null;

      if (_ddPath.length === 0) {
        // State level
        labels = Object.keys(tree).sort();
        labels.forEach(function(state) {
          const districts = (tree[state] || {}).districts || {};
          let total = 0;
          Object.values(districts).forEach(function(ds) { total += _userFilteredCount(ds.users, userFilter); });
          values.push(total);
        });
        onClick = function(label) { _setDrilldownPath([label]); };
      } else if (_ddPath.length === 1) {
        // District level within selected state
        const state = _ddPath[0];
        const districts = (tree[state] || {}).districts || {};
        labels = Object.keys(districts).sort();
        labels.forEach(function(district) {
          values.push(_userFilteredCount(districts[district].users, userFilter));
        });
        onClick = function(label) { _setDrilldownPath([_ddPath[0], label]); };
      } else {
        // User level within selected state + district
        const state = _ddPath[0];
        const district = _ddPath[1];
        const users = ((tree[state] || {}).districts || {})[district] || {};
        const usersDict = users.users || {};
        labels = Object.keys(usersDict).sort();
        if (userFilter) labels = labels.filter(function(u) { return u === userFilter; });
        labels.forEach(function(u) { values.push(usersDict[u] || 0); });
        onClick = null; // leaf level
      }

      const COLORS = ['#00a89d','#7c3aed','#f59e0b','#ef4444','#10b981','#3b82f6','#ec4899','#6366f1'];
      if (_charts['chart-drilldown']) _charts['chart-drilldown'].destroy();
      const el = document.getElementById('chart-drilldown');
      const ctx = el ? el.getContext('2d') : null;
      if (!ctx) return;
      _charts['chart-drilldown'] = new Chart(ctx, {
        type: 'bar',
        data: { labels, datasets: [{ data: values, backgroundColor: COLORS.slice(0, Math.max(labels.length, 1)) }] },
        options: {
          responsive: true,
          plugins: { legend: { display: false } },
          scales: { y: { beginAtZero: true } },
          onClick: onClick ? function(evt, elements) {
            if (!elements.length) return;
            const idx = elements[0].index;
            onClick(labels[idx]);
          } : undefined,
        }
      });
    }

    function openDrilldownSummary() {
      if (!_ddData) return;
      const s = _ddData.summary || {};
      document.getElementById('dds-total-patients').textContent = s.total_patients ?? '--';
      document.getElementById('dds-total-measurements').textContent = s.total_measurements ?? '--';
      document.getElementById('dds-completion-rate').textContent = (s.completion_rate_pct != null ? s.completion_rate_pct + '%' : '--');
      document.getElementById('dds-period').textContent = (s.date_from || s.date_to) ? ((s.date_from || '...') + ' to ' + (s.date_to || '...')) : 'All time';
      document.getElementById('drilldown-summary-modal').style.display = 'flex';
    }

    // ── History loading ──
    let historyLoaded = false;
    let _allRuns = [];

    function _renderHistoryTable(runs) {
      const container = document.getElementById('history-content');
      if (runs.length === 0) {
        container.innerHTML = '<div class="history-empty">' + T('no_runs_found') + '</div>';
        return;
      }
      let html = '<table class="meas-table"><thead><tr><th>' + T('th_run_id') + '</th><th>' + T('th_patient') + '</th><th>' + T('th_date') + '</th><th>' + T('th_foot_length_lr') + '</th><th>' + T('th_actions') + '</th></tr></thead><tbody>';
      for (const run of runs) {
        html += '<tr>';
        html += '<td style="font-size:0.78rem;color:var(--muted);">' + run.run_id + '</td>';
        html += '<td>' + (run.patient_name || run.patient_id) + '</td>';
        html += '<td>' + (run.date || '--') + '</td>';
        html += '<td class="num">' + (run.foot_length_left || '--') + ' / ' + (run.foot_length_right || '--') + '</td>';
        html += '<td style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">';
        html += '<a href="/report/' + run.run_id + '" target="_blank" style="color:var(--accent);text-decoration:none;font-size:0.84rem;">' + T('btn_print_pdf') + '</a>';
        if (run.json_url) html += '<a href="' + run.json_url + '" target="_blank" style="color:var(--accent);text-decoration:none;font-size:0.84rem;">' + T('btn_download_json') + '</a>';
        html += '<button class="btn-secondary tbl-action-btn" style="font-size:0.78rem;padding:3px 8px;" data-run-id="' + run.run_id + '" onclick="openEditModal(this.dataset.runId)">Edit</button>';
        html += '</td>';
        html += '</tr>';
      }
      html += '</tbody></table>';
      container.innerHTML = html;
    }

    function filterHistory() {
      const search  = ((document.getElementById('hist-search') || {}).value || '').toLowerCase();
      const dateFrom = (document.getElementById('hist-date-from') || {}).value || '';
      const dateTo   = (document.getElementById('hist-date-to') || {}).value || '';
      let filtered = _allRuns.filter(r => {
        const name = (r.patient_name + ' ' + r.patient_id).toLowerCase();
        if (search && !name.includes(search)) return false;
        if (dateFrom && (r.date || '') < dateFrom) return false;
        if (dateTo   && (r.date || '') > dateTo)   return false;
        return true;
      });
      _renderHistoryTable(filtered);
    }

    async function loadHistory() {
      historyLoaded = false;
      const container = document.getElementById('history-content');
      container.innerHTML = '<div style="text-align:center;padding:24px;color:var(--muted);"><span class="spinner"></span>' + T('history_loading') + '</div>';
      try {
        const r = await fetch('/api/history');
        if (!r.ok) { container.innerHTML = '<div class="history-empty">' + T('history_failed') + '</div>'; return; }
        _allRuns = await r.json();
        _renderHistoryTable(_allRuns);
        historyLoaded = true;
      } catch(e) {
        console.warn('loadHistory error:', e);
        container.innerHTML = '<div class="history-empty">' + T('history_failed') + '</div>';
      }
    }

    // ── Agent management (admin) ──
    let agentsLoaded = false;
    async function loadAgents() {
      if (agentsLoaded) return;
      const container = document.getElementById('agents-content');
      container.innerHTML = '<div style="text-align:center;padding:24px;color:var(--muted);"><span class="spinner"></span>Loading...</div>';
      try {
        const r = await fetch('/api/agents');
        if (!r.ok) { container.innerHTML = '<p style="color:var(--muted);">Access denied or failed to load.</p>'; return; }
        const agents = await r.json();
        if (agents.length === 0) {
          container.innerHTML = '<div class="history-empty">No agents registered yet.</div>';
          return;
        }
        let html = '<table class="meas-table"><thead><tr><th>Name</th><th>Username</th><th>Phone</th><th>Center</th><th>Status</th><th>Actions</th></tr></thead><tbody>';
        for (const a of agents) {
          const status = a.approved ? '<span class="badge badge-trusted">Active</span>' : '<span class="badge badge-error">Revoked</span>';
          const toggleBtn = a.approved
            ? '<button class="tbl-action-btn" onclick="toggleAgent(\\'' + a.username + '\\',false)" style="padding:4px 10px;border:1px solid var(--error);border-radius:6px;background:#fff;color:var(--error);cursor:pointer;font-size:0.78rem;">Revoke</button>'
            : '<button class="tbl-action-btn" onclick="toggleAgent(\\'' + a.username + '\\',true)" style="padding:4px 10px;border:1px solid var(--accent);border-radius:6px;background:#fff;color:var(--accent);cursor:pointer;font-size:0.78rem;">Approve</button>';
          const resetBtn = '<button class="tbl-action-btn" onclick="showResetPasswordModal(\\'' + a.username + '\\')" style="padding:4px 10px;border:1px solid var(--muted);border-radius:6px;background:#fff;color:var(--ink);cursor:pointer;font-size:0.78rem;">Reset PW</button>';
          html += '<tr><td>' + a.name + '</td><td>' + a.username + '</td><td>' + (a.phone||'--') + '</td><td>' + (a.center||'--') + '</td><td>' + status + '</td><td style="display:flex;gap:6px;">' + toggleBtn + resetBtn + '</td></tr>';
        }
        html += '</tbody></table>';
        container.innerHTML = html;
        agentsLoaded = true;
      } catch(e) {
        console.warn('loadAgents error:', e);
        container.innerHTML = '<p style="color:var(--muted);">Failed to load agents.</p>';
      }
    }
    async function toggleAgent(username, approve) {
      const action = approve ? 'approve' : 'revoke';
      try {
        await fetch('/api/agents/' + username + '/' + action, { method: 'POST' });
        agentsLoaded = false;
        loadAgents();
      } catch(e) { console.warn('toggleAgent error:', e); }
    }
    function showResetPasswordModal(username) {
      document.getElementById('reset-pw-username').value = username;
      document.getElementById('reset-pw-modal-label').textContent = 'Reset password for: ' + username;
      document.getElementById('reset-pw-new').value = '';
      document.getElementById('reset-pw-error').textContent = '';
      document.getElementById('reset-pw-modal').style.display = 'flex';
    }
    async function submitResetPassword() {
      const username = document.getElementById('reset-pw-username').value;
      const pw = document.getElementById('reset-pw-new').value.trim();
      if (pw.length < 8) { document.getElementById('reset-pw-error').textContent = 'Min 8 characters.'; return; }
      const fd = new FormData();
      fd.append('new_password', pw);
      const r = await fetch('/api/agents/' + username + '/reset-password', { method: 'POST', body: fd });
      const d = await r.json();
      if (r.ok) {
        document.getElementById('reset-pw-modal').style.display = 'none';
        alert('Password reset for ' + username + '. They will be prompted to change it on next login.');
      } else {
        document.getElementById('reset-pw-error').textContent = d.detail || 'Failed.';
      }
    }

    // ── New Patient (reset form) ──
    function resetPredictionForm() {
      const form = document.getElementById('run-form');
      form.reset();
      _validatedSlots.clear();
      Object.keys(_retakeCount).forEach(k => delete _retakeCount[k]);
      // Clear previews
      document.querySelectorAll('.preview-img').forEach(img => { img.src = ''; img.style.display = 'none'; });
      document.querySelectorAll('.file-name').forEach(el => { el.textContent = ''; });
      document.querySelectorAll('.upload-cell').forEach(el => { el.classList.remove('has-file'); });
      // Hide all per-slot validation badges (otherwise stale "uploaded" badges
      // from a previous run appear on the fresh form even before any file is
      // selected for the new patient).
      document.querySelectorAll('.validate-badge').forEach(b => {
        b.style.display = 'none';
        b.className = 'validate-badge';
        b.textContent = '';
      });
      // Hide results — use classList.remove('visible') so subsequent runs can
      // re-show via the same '.visible' rule. Setting style.display='none'
      // directly here would override the CSS class on the next run and the
      // result panel would never reappear.
      const resultEl = document.getElementById('result');
      if (resultEl) resultEl.classList.remove('visible');
      // Re-set today's date
      const dateInput = form.querySelector('input[name="exam_date"]');
      if (dateInput) dateInput.value = new Date().toISOString().slice(0,10);
      // Re-set hidden defaults
      const bs = form.querySelector('input[name="allow_borrowed_scale"]');
      if (bs) bs.value = 'true';
      const lm = form.querySelector('input[name="lenient_mode"]');
      if (lm) lm.value = 'true';
      // Clear status
      const statusEl = document.getElementById('status');
      if (statusEl) { statusEl.textContent = ''; statusEl.className = 'status'; }
    }

    // ── Prediction form (preserved from original) ──
    const form         = document.getElementById("run-form");
    const statusEl     = document.getElementById("status");
    const resultEl     = document.getElementById("result");
    const resultHeader = document.getElementById("result-header");
    const patientInfoSummary = document.getElementById("patient-info-summary");
    const measContainer  = document.getElementById("meas-container");
    const warningsContainer = document.getElementById("warnings-container");
    const jsonContainer  = document.getElementById("json-container");
    const submitBtn    = document.getElementById("submit-btn");
    const progressWrap = document.getElementById("progress-wrap");
    const progressFill = document.getElementById("progress-fill");
    const progressLabel = document.getElementById("progress-label");

    // Camera-vs-gallery choice sheet — tapping any of the 6 photo cells asks
    // the user which source to use instead of jumping straight to the camera.
    let _photoSourceTargetKey = null;
    function openPhotoSource(key) {
      _photoSourceTargetKey = key;
      document.getElementById('photo-source-overlay').style.display = 'flex';
    }
    function closePhotoSource() {
      document.getElementById('photo-source-overlay').style.display = 'none';
      _photoSourceTargetKey = null;
    }
    function choosePhotoSource(source) {
      const key = _photoSourceTargetKey;
      document.getElementById('photo-source-overlay').style.display = 'none';
      if (!key) return;
      const picker = document.getElementById(source === 'camera' ? 'shared-camera-input' : 'shared-gallery-input');
      picker.onchange = function() {
        if (picker.files.length) {
          const targetInput = document.getElementById('input-' + key);
          const dt = new DataTransfer();
          dt.items.add(picker.files[0]);
          targetInput.files = dt.files;
          markFile(targetInput, key);
        }
        picker.value = '';
      };
      picker.click();
    }

    function markFile(input, key) {
      const cell = document.getElementById("cell-" + key);
      const fn   = document.getElementById("fn-" + key);
      const prev = document.getElementById("prev-" + key);
      const badge = document.getElementById("badge-" + key);
      if (input.files.length) {
        cell.classList.add("has-file");
        fn.textContent = input.files[0].name;
        const reader = new FileReader();
        reader.onload = (e) => { prev.src = e.target.result; };
        reader.readAsDataURL(input.files[0]);
        // No per-upload validation - pipeline validates internally during
        // inference. Skipping the validate-view call removes ~1-2s latency
        // per image and prevents false-positive "low quality" warnings.
        _validatedSlots.add(key);
        if (badge) { badge.className = "validate-badge ok"; badge.textContent = "\u2713 uploaded"; badge.style.display = ""; }
      } else {
        cell.classList.remove("has-file");
        fn.textContent = "";
        prev.src = "";
        _validatedSlots.delete(key);
        delete _retakeCount[key];
        if (badge) { badge.style.display = "none"; }
      }
    }

    // _validateSlot kept as a no-op for backward compatibility with any
    // leftover callers; per-upload validation has been removed entirely.
    async function _validateSlot(key, file) { /* no-op */ }

        // Shows the retake-modal and decides whether to expose the "Use Anyway"
    // button based on how many times this slot has been re-uploaded.
    // slot: slot key (e.g. "left_plantar"), msgHtml: HTML for the modal body.
    function _showRetakeModal(slot, msgHtml) {
      if (slot) {
        _retakeCount[slot] = (_retakeCount[slot] || 0) + 1;
        _retakeCurrentSlot = slot;
      } else {
        _retakeCurrentSlot = null;
      }
      document.getElementById('retake-msg').innerHTML = msgHtml;
      const useAnywayBtn = document.getElementById('retake-use-anyway-btn');
      if (useAnywayBtn) {
        const showOverride = slot && _retakeCount[slot] >= RETAKE_LIMIT;
        useAnywayBtn.style.display = showOverride ? 'inline-block' : 'none';
      }
      document.getElementById('retake-modal').style.display = 'flex';
    }

    // Called when the user clicks "Use this anyway" — marks the current slot
    // as validated so form submission proceeds despite quality warnings.
    window.useImageAnyway = function() {
      if (_retakeCurrentSlot) {
        _validatedSlots.add(_retakeCurrentSlot);
        const badge = document.getElementById("badge-" + _retakeCurrentSlot);
        if (badge) {
          badge.className = "validate-badge warn";
          badge.textContent = "\u26a0 used (low quality)";
          badge.style.display = "";
        }
      } else {
        // Submission-blocker path: bypass for every filled slot so the
        // immediate retry of the form submit succeeds. Previously this did
        // nothing because _retakeCurrentSlot was null, leaving the user stuck.
        ['left_plantar','left_dorsal','left_medial','right_plantar','right_dorsal','right_medial'].forEach(function(k){
          var inp = document.getElementById('input-' + k);
          if (inp && inp.files.length > 0) {
            _validatedSlots.add(k);
            var b = document.getElementById("badge-" + k);
            if (b) {
              b.className = "validate-badge warn";
              b.textContent = "\u26a0 used (low quality)";
              b.style.display = "";
            }
          }
        });
      }
      document.getElementById('retake-modal').style.display = 'none';
      // Auto-resubmit so the user does not have to click submit again.
      var formEl = document.getElementById('run-form');
      if (formEl && typeof formEl.requestSubmit === 'function') formEl.requestSubmit();
    };

    // Called when the user clicks "Retake Photo" — closes the modal and
    // re-opens the file picker for the slot that triggered the warning.
    window.retakeCurrentSlot = function() {
      document.getElementById('retake-modal').style.display = 'none';
      if (_retakeCurrentSlot) {
        const inp = document.getElementById('input-' + _retakeCurrentSlot);
        if (inp) inp.click();
      } else {
        // Submission-blocker path: highlight unvalidated cells so the user
        // taps the correct view (was: silent close, user tapped wrong cell).
        ['left_plantar','left_dorsal','left_medial','right_plantar','right_dorsal','right_medial'].forEach(function(k){
          var inp = document.getElementById('input-' + k);
          var cell = document.getElementById('cell-' + k);
          if (inp && inp.files.length > 0 && !_validatedSlots.has(k) && cell) {
            cell.style.outline = '3px solid var(--warn-text)';
            cell.style.outlineOffset = '2px';
            setTimeout(function(){ cell.style.outline = ''; cell.style.outlineOffset = ''; }, 4000);
          }
        });
      }
    };

    function _retakeMsg(result) {
      const issues = result.issues || [];
      const lines = [];
      if (!result.detected_view || (result.match_score > 0 && result.match_score < 0.15)) {
        lines.push('<b>Not recognised as a foot photo.</b> This image does not appear to contain a foot. Please upload a foot image from the correct angle.');
      } else {
        // Image-quality issues (Layer 1/2/3) — show first because they're the
        // most concrete fix the clinician can make right away.
        if (issues.includes('blurry')) {
          lines.push('<b>Image is blurry.</b> Hold the phone steady and tap the foot to focus before capturing.');
        }
        if (issues.includes('too_dark')) {
          lines.push('<b>Too dark.</b> Move to a brighter spot or turn on the light. Avoid shadows on the foot.');
        }
        if (issues.includes('overexposed')) {
          lines.push('<b>Too bright / washed out.</b> Move out of direct sunlight or away from a bright lamp. Re-capture with even, indirect light.');
        }
        if (issues.includes('low_contrast') || issues.includes('tonally_flat')) {
          lines.push('<b>Low contrast.</b> Use a plain background that contrasts with the skin (e.g. dark cloth on a light floor, or vice versa).');
        }
        if (issues.includes('noisy') || issues.includes('noisy_structural')) {
          lines.push('<b>Image too grainy.</b> Light is too low for the camera. Move to a brighter spot — graininess hides the foot edge.');
        }
        if (issues.includes('marker_too_small')) {
          lines.push('<b>Camera too far from the foot.</b> The reference card looks small in the photo. Move closer so the foot fills most of the frame, with the card next to it.');
        }
        if (issues.includes('low_mask_conf')) {
          lines.push('<b>Poor image clarity.</b> The foot outline is unclear — image may be blurry, too dark, or the foot is partially out of frame. Ensure even lighting and the full foot is visible.');
        }
        if (issues.includes('no_reference_match')) {
          lines.push('<b>Angle not recognised.</b> The view angle does not match plantar (sole), dorsal (top), or medial (side). Hold the camera perpendicular to the foot and capture only that view.');
        }
        if (issues.includes('no_card')) {
          lines.push('<b>Reference card missing.</b> Place a standard credit/debit card flat on the same surface as the foot — not held in hand. This is needed for accurate measurements.');
        } else if (issues.includes('card_misplaced')) {
          lines.push('<b>Reference card position incorrect.</b> The card appears tilted or not coplanar with the foot. Lay it flat beside the foot on the same surface.');
        }
      }
      return lines.length ? lines.join('<br><br>') : '<b>Low confidence.</b> Image quality is insufficient for reliable measurement. Retake with better lighting and ensure the full foot is in frame.';
    }

    // ── Per-slot validation state ──────────────────────────────────────────
    // slots validated as feet via /api/validate-view (or via "Use Anyway")
    const _validatedSlots = new Set();
    // Per-slot retake attempts. After RETAKE_LIMIT failed attempts the user
    // can override and submit anyway (e.g. low-light field conditions where
    // a perfect shot isn't possible). Resets when the slot is cleared.
    const _retakeCount = {};
    const RETAKE_LIMIT = 3;
    // Set just before opening the retake-modal so the "Use Anyway" button
    // knows which slot to bypass-validate.
    let _retakeCurrentSlot = null;

    function _setCardWarn(key, show) {
      // No-op: ArUco card is always present in field uploads. The detector
      // sometimes misses it on oblique medial shots, but the pipeline borrows
      // scale from other views — the agent doesn't need a per-view warning.
      // Function kept as a no-op to avoid breaking any leftover callers.
    }

    // ── Sample image help popup ──
    const SAMPLE_TITLES = {
      plantar: "Plantar (sole) \u2014 Sample",
      dorsal:  "Dorsal (top) \u2014 Sample",
      medial:  "Medial (inner) \u2014 Sample",
    };
    function showSample(side, view) {
      const title = SAMPLE_TITLES[view] || view;
      const file = side + "_" + view + ".jpeg";
      document.getElementById("sample-modal-title").textContent = title;
      document.getElementById("sample-modal-img").src = "/samples/" + file;
      document.getElementById("sample-modal-overlay").classList.add("visible");
    }
    function closeSample() {
      document.getElementById("sample-modal-overlay").classList.remove("visible");
    }
    document.addEventListener("keydown", function(e) {
      if (e.key === "Escape") closeSample();
    });

    // Auto-fill today's date
    const dateInput = form.querySelector('input[name="exam_date"]');
    if (dateInput && !dateInput.value) {
      dateInput.value = new Date().toISOString().split("T")[0];
    }

    const STAGE_KEYS = {
      preprocessing: "stage_preprocessing",
      segmentation:  "stage_segmentation",
      reference:     "stage_reference",
      landmarks:     "stage_landmarks",
      geometry:      "stage_geometry",
      complete:      "stage_complete",
    };

    function showProgress(pct, stage, view) {
      progressWrap.classList.add("visible");
      progressFill.style.width = pct + "%";
      let label = T(STAGE_KEYS[stage] || stage) || stage;
      if (view) label += " \\u2014 " + view.replace("_", " ");
      label += "  (" + pct + "%)";
      progressLabel.textContent = label;
    }
    function hideProgress() {
      progressWrap.classList.remove("visible");
      progressFill.style.width = "0%";
      progressLabel.textContent = "";
    }

    function displayResult(data) {
      statusEl.textContent = T("status_complete");
      const r0 = data.result || data;
      const hasMeasResult = (r0.left && r0.left.foot_length_mm) || (r0.right && r0.right.foot_length_mm);
      resultHeader.innerHTML =
        '<div class="meta-links">' +
          '<a href="' + data.compact_json_url + '" target="_blank">Compact JSON</a>' +
          '<a href="' + data.full_json_url + '" target="_blank">Full JSON</a>' +
          '<span style="color:var(--muted)">Run: ' + data.run_id + '</span>' +
        '</div>';

      const fd = new FormData(form);
      const pName = fd.get("patient_name") || "";
      const pAge  = fd.get("age") || "";
      const pGender = fd.get("gender") || "";
      const pDiab = fd.get("diabetes") || "no";
      const pAmput = fd.get("amputated_toes") || "no";
      const pAbha = fd.get("abha_id") || "";
      const pCenter = fd.get("capture_center") || "";
      const pDoctor = fd.get("referring_doctor") || "";
      const pDate = fd.get("exam_date") || "";
      let psHTML = '<div class="patient-summary">';
      psHTML += '<div class="ps-item"><span class="ps-label">Patient:</span><span class="ps-value">' + data.patient_id + (pName ? " \\u2014 " + pName : "") + '</span></div>';
      if (pAge) psHTML += '<div class="ps-item"><span class="ps-label">Age:</span><span class="ps-value">' + pAge + ' yrs</span></div>';
      if (pGender) psHTML += '<div class="ps-item"><span class="ps-label">Gender:</span><span class="ps-value">' + pGender.charAt(0).toUpperCase() + pGender.slice(1) + '</span></div>';
      if (pAbha) psHTML += '<div class="ps-item"><span class="ps-label">ABHA ID:</span><span class="ps-value">' + pAbha + '</span></div>';
      psHTML += '<div class="ps-item"><span class="ps-label">Diabetes:</span><span class="ps-value">' + (pDiab === "no" ? "No" : "Yes") + '</span></div>';
      psHTML += '<div class="ps-item"><span class="ps-label">Amputated Toes:</span><span class="ps-value">' + (pAmput === "no" ? "No" : "Yes") + '</span></div>';
      if (pCenter) psHTML += '<div class="ps-item"><span class="ps-label">Center:</span><span class="ps-value">' + pCenter + '</span></div>';
      if (pDoctor) psHTML += '<div class="ps-item"><span class="ps-label">Doctor:</span><span class="ps-value">' + pDoctor + '</span></div>';
      if (pDate) psHTML += '<div class="ps-item"><span class="ps-label">Exam date:</span><span class="ps-value">' + pDate + '</span></div>';
      psHTML += '</div>';
      patientInfoSummary.innerHTML = psHTML;

      const LABELS = {
        foot_length_mm: T("meas_foot_length"),
        forefoot_width_mm: T("meas_forefoot_width"),
        heel_width_mm: T("meas_heel_width"),
        midfoot_width_mm: T("meas_midfoot_width"),
        toe_axis_angle_deg: T("meas_toe_axis"),
        ball_girth_mm_provisional: T("meas_ball_girth"),
        instep_girth_mm_provisional: T("meas_instep_girth"),
        malleoli_height_mm: T("meas_malleoli_height"),
      };
      const UNITS = {
        foot_length_mm: "cm", forefoot_width_mm: "cm",
        heel_width_mm: "cm", midfoot_width_mm: "cm",
        toe_axis_angle_deg: "\\u00b0",
        ball_girth_mm_provisional: "cm",
        instep_girth_mm_provisional: "cm",
        malleoli_height_mm: "cm",
      };
      const r = data.result || data;
      let t = '<table class="meas-table"><thead><tr><th>' + T("meas_measurement") + '</th><th style="text-align:right">' + T("meas_left") + '</th><th style="text-align:right">' + T("meas_right") + '</th></tr></thead><tbody>';
      // Implausible measurements (sanity-gate rejections) render as a
      // plain em-dash. Verbose per-row reasons + summary panel were
      // removed: upload-time validate-view modal is the user-facing QC
      // checkpoint, and post-hoc rejection text is not actionable.
      function _renderCell(entry, unit) {
        const ok = entry && typeof entry.value_mm === "number";
        if (ok) {
          const v = unit === "cm" ? (entry.value_mm / 10).toFixed(2) : entry.value_mm.toFixed(1);
          return v + " " + unit;
        }
        return "\u2014";
      }
      for (const [key, label] of Object.entries(LABELS)) {
        const lv = r.left && r.left[key];
        const rv = r.right && r.right[key];
        const unit = UNITS[key] || "mm";
        const isProv = key.includes("provisional");
        const cls = isProv ? ' class="prov"' : '';
        const lStr = _renderCell(lv, unit);
        const rStr = _renderCell(rv, unit);
        const provTag = isProv ? " *" : "";
        t += '<tr' + cls + '><td>' + label + provTag + '</td><td class="num">' + lStr + '</td><td class="num">' + rStr + '</td></tr>';
      }
      t += '</tbody></table>';

      if (Object.keys(LABELS).some(k => k.includes("provisional"))) {
        t += '<div style="font-size:0.78rem;color:var(--muted);margin-top:6px;">* ' + T("meas_provisional") + '</div>';
      }
      // ── Footwear preparation (technician) table ──
      // Same fallback rule used by the report endpoint: prefer AI value;
      // fall back to manual entry if the AI value was rejected by sanity gate.
      const _manualMeas = (data.patient_info && data.patient_info.manual_measurements) || {};
      function _manualMm(side, mkey) {
        const v = (_manualMeas[mkey] || {})[side];
        if (v === undefined || v === null || v === "") return null;
        const f = parseFloat(v);
        return isFinite(f) ? f * 10.0 : null;  // form values are in cm; convert to mm
      }
      function _aiOrManual(side, aiKey, mKey) {
        const ai = (r[side] || {})[aiKey];
        if (ai && typeof ai.value_mm === "number" && ai.quality !== "rejected_implausible") {
          return { value: ai.value_mm, source: "ai" };
        }
        const mv = _manualMm(side, mKey);
        if (mv !== null) return { value: mv, source: "manual" };
        return { value: null, source: null };
      }
      function _techCell(side) {
        const fl = _aiOrManual(side, "foot_length_mm",             "foot_length");
        const bg = _aiOrManual(side, "ball_girth_mm_provisional",  "ball_girth");
        const ig = _aiOrManual(side, "instep_girth_mm_provisional","instep_girth");
        const mh = _aiOrManual(side, "malleoli_height_mm",         "malleoli_height");
        return {
          fl_plus2:  fl.value !== null ? { value: fl.value + 20.0, source: fl.source } : { value: null, source: null },
          bg_60:     bg.value !== null ? { value: bg.value * 0.60, source: bg.source } : { value: null, source: null },
          ig_85:     ig.value !== null ? { value: ig.value * 0.85, source: ig.source } : { value: null, source: null },
          mh:        mh,
        };
      }
      const techL = _techCell("left");
      const techR = _techCell("right");
      function _fmtTech(c) {
        if (c.value === null) return "—";
        const cm = (c.value / 10).toFixed(1) + " cm";
        return c.source === "manual"
          ? cm + ' <span style="font-size:0.72rem;color:var(--warn-text);background:#fef3c7;padding:1px 5px;border-radius:3px;margin-left:4px;">' + T("tech_from_manual") + '</span>'
          : cm;
      }
      const techRows = [
        [T("tech_foot_length_plus2"),  techL.fl_plus2, techR.fl_plus2],
        [T("tech_ball_girth_60pct"),   techL.bg_60,    techR.bg_60],
        [T("tech_instep_girth_85pct"), techL.ig_85,    techR.ig_85],
        [T("tech_malleoli_height"),    techL.mh,       techR.mh],
      ];
      const anyTech = techRows.some(row => row[1].value !== null || row[2].value !== null);
      if (anyTech) {
        t += '<div style="margin-top:18px;font-weight:600;font-size:0.95rem;color:var(--ink);">' + T("tech_table_title") + '</div>';
        t += '<table class="meas-table" style="margin-top:6px;"><thead><tr><th>' + T("meas_measurement") + '</th><th style="text-align:right">' + T("meas_left") + '</th><th style="text-align:right">' + T("meas_right") + '</th></tr></thead><tbody>';
        for (const [label, lc, rc] of techRows) {
          t += '<tr><td>' + label + '</td><td class="num">' + _fmtTech(lc) + '</td><td class="num">' + _fmtTech(rc) + '</td></tr>';
        }
        t += '</tbody></table>';
        t += '<div style="font-size:0.78rem;color:var(--muted);margin-top:6px;">' + T("tech_explainer") + '</div>';
      }
      // ── Cross-foot sanity check ──
      const lLen = r.left && r.left.foot_length_mm ? r.left.foot_length_mm.value_mm : null;
      const rLen = r.right && r.right.foot_length_mm ? r.right.foot_length_mm.value_mm : null;
      if (lLen && rLen && lLen > 0) {
        const ratio = rLen / lLen;
        if (ratio > 1.25 || ratio < 0.75) {
          const suspect = ratio > 1.25 ? 'Right' : 'Left';
          t += '<div style="margin-top:10px;padding:10px 14px;background:#fef3c7;border-left:4px solid #f59e0b;border-radius:4px;color:var(--warn-text);font-size:0.85rem;">'
             + '<strong>&#9888; Warning:</strong> Significant left-right difference detected (L: '
             + (lLen/10).toFixed(1) + ' cm, R: ' + (rLen/10).toFixed(1) + ' cm). '
             + suspect + ' foot measurements may be unreliable due to scale detection issues. '
             + 'Consider re-capturing ' + suspect.toLowerCase() + ' foot images.</div>';
        }
      }
      measContainer.innerHTML = t;
      warningsContainer.innerHTML = '';

      jsonContainer.innerHTML = '<details><summary>' + T("full_json_output") + '</summary><pre>' + JSON.stringify(r, null, 2) + '</pre></details>';

      // ── Render segmentation overlays ──
      const VIEW_NAMES = {left_plantar:"Left Plantar",left_dorsal:"Left Dorsal",left_medial:"Left Medial",right_plantar:"Right Plantar",right_dorsal:"Right Dorsal",right_medial:"Right Medial"};
      const segGrid = document.getElementById("viz-seg-grid");
      const segPanel = document.getElementById("viz-seg-panel");
      const lmGrid = document.getElementById("viz-lm-grid");
      const lmPanel = document.getElementById("viz-lm-panel");
      segGrid.innerHTML = ""; lmGrid.innerHTML = "";
      const segImgs = data.viz_seg || {};
      const lmImgs = data.viz_lm || {};
      if (Object.keys(segImgs).length > 0) {
        for (const [k, url] of Object.entries(segImgs)) {
          segGrid.innerHTML += '<div class="viz-card"><img src="' + url + '" alt="' + k + '" onclick="window.open(this.src)"><div class="viz-label">' + (VIEW_NAMES[k]||k) + '</div></div>';
        }
        segPanel.style.display = "block";
      } else { segPanel.style.display = "none"; }
      if (Object.keys(lmImgs).length > 0) {
        for (const [k, url] of Object.entries(lmImgs)) {
          lmGrid.innerHTML += '<div class="viz-card"><img src="' + url + '" alt="' + k + '" onclick="window.open(this.src)"><div class="viz-label">' + (VIEW_NAMES[k]||k) + '</div></div>';
        }
        lmPanel.style.display = "block";
      } else { lmPanel.style.display = "none"; }

      // ── Result action buttons ──
      const actionsEl = document.getElementById("result-actions");
      actionsEl.innerHTML =
        '<button class="btn-secondary" onclick="window.open(\\'/report/' + data.run_id + '\\',\\'_blank\\')">' + T("btn_print_pdf") + '</button>' +
        '<a class="btn-secondary" href="' + data.compact_json_url + '" target="_blank">' + T("btn_download_json") + '</a>';

      resultEl.classList.add("visible");

      // Refresh dashboard data on next visit
      dashboardLoaded = false;
    }

    var _isSubmitting = false;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      // Hammer-click guard. submitBtn.disabled below races with rapid clicks.
      if (_isSubmitting) return;

      // Block submission if any filled slot was not validated as a foot
      const ALL_SLOTS = ['left_plantar','left_dorsal','left_medial','right_plantar','right_dorsal','right_medial'];
      const unvalidatedSlots = ALL_SLOTS.filter(k => {
        const inp = document.getElementById('input-' + k);
        return inp && inp.files.length > 0 && !_validatedSlots.has(k);
      });
      if (unvalidatedSlots.length > 0) {
        // Submission blocker — multiple slots fail at once. Always offer the
        // "Use this anyway" override here so the user is never stuck.
        _showRetakeModal(null,
          '<b>The following images were not verified as foot photos:</b><br><br>' +
          unvalidatedSlots.map(function(k){ return '&bull; ' + k.replace('_', ' '); }).join('<br>') +
          '<br><br>Tap <b>Retake</b> to highlight the affected cells and re-upload, or <b>Use this anyway</b> to submit and let the pipeline process them as-is.'
        );
        // Force-show the override button (default is hidden until RETAKE_LIMIT).
        var _btn = document.getElementById('retake-use-anyway-btn');
        if (_btn) _btn.style.display = 'inline-block';
        return;
      }

      // Manual-measurements reminder. Soft prompt only — never blocks.
      // Triggered when ALL 8 manual fields are empty (clinician forgot to enter
      // tape readings). Per-side or per-measurement gaps are normal and silent.
      var _manualNames = [
        'manual_foot_length_left','manual_foot_length_right',
        'manual_ball_girth_left','manual_ball_girth_right',
        'manual_instep_girth_left','manual_instep_girth_right',
        'manual_malleoli_height_left','manual_malleoli_height_right',
      ];
      var _manualEmpty = _manualNames.every(function(n) {
        var el = form.querySelector('[name="' + n + '"]');
        return !el || !String(el.value).trim();
      });
      if (_manualEmpty) {
        var _ok = window.confirm('No manual tape measurements entered. Submit anyway?');
        if (!_ok) return;
      }

      _isSubmitting = true;
      statusEl.textContent = T("status_uploading");
      statusEl.className = "status";
      submitBtn.disabled = true;
      resultEl.classList.remove("visible");
      resultHeader.innerHTML = "";
      patientInfoSummary.innerHTML = "";
      measContainer.innerHTML = "";
      warningsContainer.innerHTML = "";
      jsonContainer.innerHTML = "";
      document.getElementById("viz-seg-grid").innerHTML = "";
      document.getElementById("viz-lm-grid").innerHTML = "";
      document.getElementById("viz-seg-panel").style.display = "none";
      document.getElementById("viz-lm-panel").style.display = "none";
      document.getElementById("result-actions").innerHTML = "";
      document.getElementById("duplicate-warning-banner").style.display = "none";
      hideProgress();

      let es = null;
      try {
        const resp = await fetch("/predict", { method: "POST", body: new FormData(form) });
        const init = await resp.json();
        if (!resp.ok) throw new Error(init.detail || "Failed to start inference.");

        const runId = init.run_id;

        // Show duplicate warning if a record for this patient+date already exists
        const dupBanner = document.getElementById("duplicate-warning-banner");
        if (init.duplicate_warning) {
          dupBanner.innerHTML = '<div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">' +
            '<div>\u26a0\ufe0f A record for this patient on this exam date already exists (run: <b>' +
            init.duplicate_warning + '</b>). ' +
            '<a href="/report/' + init.duplicate_warning + '" target="_blank" style="color:#856404;font-weight:600;">View existing run</a> &nbsp;|&nbsp; ' +
            'continuing with new submission\u2026</div>' +
            '<button onclick="this.closest(\\'#duplicate-warning-banner\\').style.display=\\'none\\'" style="background:transparent;border:none;color:#856404;font-size:1.2rem;cursor:pointer;padding:0 4px;line-height:1;" title="Dismiss">&times;</button>' +
            '</div>';
          dupBanner.style.display = '';
        } else {
          dupBanner.style.display = 'none';
        }

        statusEl.textContent = T("status_running");
        showProgress(0, "preprocessing", null);

        await new Promise((resolve, reject) => {
          es = new EventSource("/progress/" + runId);
          es.onmessage = (e) => {
            let msg;
            try { msg = JSON.parse(e.data); } catch(e) { return; }
            if (msg.status === "complete") {
              showProgress(100, "complete", null);
              es.close();
              resolve(msg.payload);
            } else if (msg.status === "error") {
              es.close();
              reject(new Error(msg.error || "Pipeline error."));
            } else {
              showProgress(msg.percent || 0, msg.stage || "", msg.view || null);
            }
          };
          es.onerror = () => { es.close(); reject(new Error("Lost connection to server.")); };
        }).then((payload) => {
          hideProgress();
          displayResult(payload);
        });
      } catch (error) {
        if (es) es.close();
        hideProgress();
        statusEl.textContent = error.message;
        statusEl.className = "status error";
      } finally {
        submitBtn.disabled = false;
        _isSubmitting = false;
      }
    });

    // ── Init language ──
    (function() {
      const savedLang = localStorage.getItem('lepra-lang');
      if (savedLang && savedLang !== 'en') {
        setLanguage(savedLang);
      }
    })();

    // ── Expose onclick handlers globally ──
    window.setTheme = setTheme;
    window.resetPredictionForm = resetPredictionForm;
    window.showSample = showSample;
    window.closeSample = closeSample;
    window.toggleAgent = toggleAgent;
    window.setLanguage = setLanguage;
    window.markFile = markFile;

    // ── Load centers for State/Center dropdowns ──
    (async function loadCenters() {
      try {
        const r = await fetch('/api/centers');
        if (!r.ok) return;
        const data = await r.json();
        const stateEl = document.getElementById('state-select');
        const districtEl = document.getElementById('district-select');
        const centerEl = document.getElementById('center-select');
        if (!stateEl || !centerEl) return;
        const centersMap = data.centers || {};
        const districtsMap = data.districts || {};
        const staffMap = data.staff || {};
        const capturedByEl = document.getElementById('captured-by-select');
        const otherInput = document.getElementById('captured-by-other');
        (data.states || []).forEach(function(s) {
          var o = document.createElement('option');
          o.value = s; o.textContent = s;
          stateEl.appendChild(o);
        });
        stateEl.addEventListener('change', function() {
          if (districtEl) {
            districtEl.innerHTML = '<option value="">-- Select District --</option>';
            var dlist = districtsMap[stateEl.value] || [];
            dlist.forEach(function(d) {
              var o = document.createElement('option');
              o.value = d; o.textContent = d;
              districtEl.appendChild(o);
            });
          }
          centerEl.innerHTML = '<option value="">-- Select Center --</option>';
          var list = centersMap[stateEl.value] || [];
          list.forEach(function(c) {
            var o = document.createElement('option');
            o.value = c; o.textContent = c;
            centerEl.appendChild(o);
          });
          if (capturedByEl) {
            capturedByEl.innerHTML = '<option value="">-- Select --</option>';
            var sList = staffMap[stateEl.value] || [];
            sList.forEach(function(name) {
              var o = document.createElement('option');
              o.value = name; o.textContent = name;
              capturedByEl.appendChild(o);
            });
            var otherOpt = document.createElement('option');
            otherOpt.value = '__other__';
            otherOpt.textContent = 'Other (not in list)';
            capturedByEl.appendChild(otherOpt);
          }
        });
        if (capturedByEl && otherInput) {
          capturedByEl.addEventListener('change', function() {
            otherInput.style.display = capturedByEl.value === '__other__' ? 'block' : 'none';
          });
        }
      } catch(e) { console.warn('loadCenters error:', e); }
    })();

    // ── Disease Type → WHO Grade conditional options ──
    (function() {
      const diseaseTypeEl = document.getElementById('disease-type-select');
      const whoGradeEl = document.getElementById('who-grade-select');
      if (!diseaseTypeEl || !whoGradeEl) return;

      const gradeOptionsMap = {
        leprosy: [
          { value: 'none',    i18n: 'opt_grade_none', text: 'None' },
          { value: 'grade_1', i18n: 'opt_grade_1',    text: 'Grade 1' },
          { value: 'grade_2', i18n: 'opt_grade_2',    text: 'Grade 2' },
        ],
        lf: [
          { value: 'none',    i18n: 'opt_grade_none', text: 'None' },
          { value: 'grade_1', i18n: 'opt_grade_1',    text: 'Grade 1' },
          { value: 'grade_2', i18n: 'opt_grade_2',    text: 'Grade 2' },
          { value: 'grade_3', i18n: 'opt_grade_3',    text: 'Grade 3' },
          { value: 'grade_4', i18n: 'opt_grade_4',    text: 'Grade 4' },
        ],
      };

      function populateGradeOptions() {
        const previous = whoGradeEl.value;
        const options = gradeOptionsMap[diseaseTypeEl.value] || gradeOptionsMap.leprosy;
        whoGradeEl.innerHTML = '';
        const blank = document.createElement('option');
        blank.value = '';
        blank.setAttribute('data-i18n', 'opt_select');
        blank.textContent = 'Select';
        whoGradeEl.appendChild(blank);
        options.forEach(function(opt) {
          var o = document.createElement('option');
          o.value = opt.value;
          o.setAttribute('data-i18n', opt.i18n);
          o.textContent = opt.text;
          whoGradeEl.appendChild(o);
        });
        // Preserve the previous selection if it still exists in the new list
        if ([...whoGradeEl.options].some(o => o.value === previous)) {
          whoGradeEl.value = previous;
        }
        if (typeof setLanguage === 'function') setLanguage(_currentLang);
      }

      diseaseTypeEl.addEventListener('change', populateGradeOptions);
      populateGradeOptions();
    })();

    // ── Init router ──
    router();

  </script>

  <!-- Retake Warning Modal -->
  <div id="retake-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.55);z-index:1100;align-items:center;justify-content:center;">
    <div style="background:var(--panel);border-radius:12px;padding:28px;width:380px;max-width:92vw;box-shadow:0 8px 32px rgba(0,0,0,0.22);text-align:center;">
      <div style="font-size:2rem;margin-bottom:10px;">&#9888;&#65039;</div>
      <div style="font-weight:700;font-size:1.05rem;margin-bottom:10px;color:var(--warn-text);">Poor Image Quality</div>
      <div id="retake-msg" style="font-size:0.9rem;color:var(--muted);margin-bottom:20px;line-height:1.6;"></div>
      <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap;">
        <button onclick="retakeCurrentSlot();" style="padding:9px 20px;background:var(--accent);color:#fff;border:none;border-radius:6px;cursor:pointer;font-weight:600;">Retake Photo</button>
        <button id="retake-use-anyway-btn" onclick="useImageAnyway();" style="display:none;padding:9px 20px;background:transparent;color:var(--muted);border:1px solid var(--line);border-radius:6px;cursor:pointer;font-weight:500;">Use this anyway</button>
      </div>
    </div>
  </div>


  <!-- Edit Patient Modal -->
  <div id="edit-patient-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:1000;align-items:center;justify-content:center;overflow-y:auto;">
    <div style="background:var(--panel);border-radius:12px;padding:28px;width:520px;max-width:94vw;box-shadow:0 8px 32px rgba(0,0,0,0.18);margin:40px auto;">
      <div style="font-weight:700;font-size:1.05rem;margin-bottom:16px;">Edit Patient Demographics</div>
      <input type="hidden" id="edit-run-id">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px 14px;margin-bottom:14px;">
        <div><label style="font-size:0.8rem;color:var(--muted);">Patient Name</label><input id="ep-patient_name" style="width:100%;padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font-size:0.9rem;" placeholder="Full name"></div>
        <div><label style="font-size:0.8rem;color:var(--muted);">Age</label><input id="ep-age" style="width:100%;padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font-size:0.9rem;" placeholder="Age"></div>
        <div><label style="font-size:0.8rem;color:var(--muted);">Gender</label>
          <select id="ep-gender" style="width:100%;padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font-size:0.9rem;">
            <option value="">Select</option><option value="male">Male</option><option value="female">Female</option><option value="other">Other</option>
          </select>
        </div>
        <div><label style="font-size:0.8rem;color:var(--muted);">Diabetes</label>
          <select id="ep-diabetes" style="width:100%;padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font-size:0.9rem;">
            <option value="">Select</option><option value="yes">Yes</option><option value="no">No</option>
          </select>
        </div>
        <div><label style="font-size:0.8rem;color:var(--muted);">Disease Type</label>
          <select id="ep-disease_type" style="width:100%;padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font-size:0.9rem;">
            <option value="leprosy">Leprosy</option><option value="lf">Lymphatic Filariasis (LF)</option>
          </select>
        </div>
        <div><label style="font-size:0.8rem;color:var(--muted);">WHO Grade</label><input id="ep-who_grade" style="width:100%;padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font-size:0.9rem;" placeholder="WHO grade"></div>
        <div><label style="font-size:0.8rem;color:var(--muted);">Amputated Toes</label><input id="ep-amputated_toes" style="width:100%;padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font-size:0.9rem;" placeholder="e.g. none"></div>
        <div><label style="font-size:0.8rem;color:var(--muted);">Exam Date</label><input id="ep-exam_date" type="date" style="width:100%;padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font-size:0.9rem;"></div>
        <div><label style="font-size:0.8rem;color:var(--muted);">Phone</label><input id="ep-phone" style="width:100%;padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font-size:0.9rem;" placeholder="Phone"></div>
        <div><label style="font-size:0.8rem;color:var(--muted);">District</label><input id="ep-district" style="width:100%;padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font-size:0.9rem;" placeholder="District"></div>
        <div><label style="font-size:0.8rem;color:var(--muted);">Village</label><input id="ep-village" style="width:100%;padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font-size:0.9rem;" placeholder="Village"></div>
        <div><label style="font-size:0.8rem;color:var(--muted);">Capture Centre</label><input id="ep-capture_center" style="width:100%;padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font-size:0.9rem;" placeholder="Centre"></div>
        <div><label style="font-size:0.8rem;color:var(--muted);">Referring Doctor</label><input id="ep-referring_doctor" style="width:100%;padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font-size:0.9rem;" placeholder="Doctor name"></div>
      </div>
      <div><label style="font-size:0.8rem;color:var(--muted);">Clinical Notes</label><textarea id="ep-clinical_notes" rows="2" style="width:100%;padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font-size:0.9rem;resize:vertical;margin-bottom:10px;" placeholder="Clinical notes"></textarea></div>
      <div id="edit-patient-error" style="color:var(--error);font-size:0.84rem;margin-bottom:10px;"></div>
      <div style="display:flex;gap:8px;">
        <button onclick="submitEditPatient()" style="flex:1;padding:10px;background:var(--accent);color:#fff;border:none;border-radius:6px;cursor:pointer;font-weight:600;">Save Changes</button>
        <button onclick="document.getElementById('edit-patient-modal').style.display='none'" style="padding:10px 16px;border:1px solid var(--line);border-radius:6px;cursor:pointer;background:var(--panel);color:var(--ink);">Cancel</button>
      </div>
    </div>
  </div>
  <script>
    async function openEditModal(runId) {
      document.getElementById('edit-run-id').value = runId;
      document.getElementById('edit-patient-error').textContent = '';
      // Clear fields first
      ['patient_name','age','gender','diabetes','disease_type','who_grade','amputated_toes',
       'exam_date','phone','district','village','capture_center','referring_doctor','clinical_notes'
      ].forEach(f => { const el = document.getElementById('ep-' + f); if(el) el.value = ''; });
      document.getElementById('edit-patient-modal').style.display = 'flex';
      try {
        const r = await fetch('/api/runs/' + runId + '/meta');
        if (!r.ok) { document.getElementById('edit-patient-error').textContent = 'Failed to load patient data.'; return; }
        const d = await r.json();
        for (const [k, v] of Object.entries(d)) {
          const el = document.getElementById('ep-' + k);
          if (el) el.value = v || '';
        }
      } catch(e) {
        document.getElementById('edit-patient-error').textContent = 'Error loading data.';
      }
    }
    async function submitEditPatient() {
      const runId = document.getElementById('edit-run-id').value;
      const errEl = document.getElementById('edit-patient-error');
      errEl.textContent = '';
      const fd = new FormData();
      ['patient_name','age','gender','diabetes','disease_type','who_grade','amputated_toes',
       'exam_date','phone','district','village','capture_center','referring_doctor','clinical_notes'
      ].forEach(f => {
        const el = document.getElementById('ep-' + f);
        if (el) fd.append(f, el.value);
      });
      try {
        const r = await fetch('/api/runs/' + runId + '/edit', { method: 'POST', body: fd });
        const res = await r.json();
        if (!r.ok) { errEl.textContent = res.detail || 'Save failed.'; return; }
        document.getElementById('edit-patient-modal').style.display = 'none';
        // Refresh history to show updated name/date
        historyLoaded = false;
        loadHistory();
      } catch(e) {
        errEl.textContent = 'Network error.';
      }
    }
  </script>

  <!-- Reset Password Modal -->
  <div id="reset-pw-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:1000;align-items:center;justify-content:center;">
    <div style="background:var(--panel);border-radius:12px;padding:28px;width:340px;max-width:90vw;box-shadow:0 8px 32px rgba(0,0,0,0.18);">
      <div id="reset-pw-modal-label" style="font-weight:700;font-size:1rem;margin-bottom:16px;"></div>
      <input type="hidden" id="reset-pw-username">
      <div style="position:relative;margin-bottom:10px;">
        <input type="password" id="reset-pw-new" placeholder="New temporary password (min 8 chars)" style="width:100%;padding:10px 42px 10px 10px;border:1px solid var(--line);border-radius:6px;font-size:0.9rem;background:var(--bg);color:var(--ink);box-sizing:border-box;">
        <button type="button" onclick="(function(){var i=document.getElementById('reset-pw-new');var s=i.type==='text';i.type=s?'password':'text';this.textContent=s?'👁':'🙈';}).call(this)" tabindex="-1" aria-label="Show password" style="position:absolute;right:8px;top:50%;transform:translateY(-50%);background:none;border:0;cursor:pointer;padding:6px;font-size:16px;color:#666;">👁</button>
      </div>
      <div id="reset-pw-error" style="color:var(--error);font-size:0.84rem;margin-bottom:10px;"></div>
      <div style="display:flex;gap:8px;">
        <button onclick="submitResetPassword()" style="flex:1;padding:10px;background:var(--accent);color:#fff;border:none;border-radius:6px;cursor:pointer;font-weight:600;">Reset Password</button>
        <button onclick="document.getElementById('reset-pw-modal').style.display='none'" style="padding:10px 16px;border:1px solid var(--line);border-radius:6px;cursor:pointer;background:var(--panel);color:var(--ink);">Cancel</button>
      </div>
    </div>
  </div>

</body>
</html>
"""


def _default_landmark_configs() -> Dict[Tuple[str, str], Tuple[str, str]]:
    view_cfg_map = {"plantar": "sole", "dorsal": "top", "medial": "side"}
    out: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for side in ("left", "right"):
        for view in ("plantar", "dorsal", "medial"):
            suffix = view_cfg_map[view]
            out[(side, view)] = (
                f"configs/{side}_{suffix}_hrnet_w32.py",
                f"checkpoints/{side}_{suffix}.pth",
            )
    return out


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip())
    cleaned = cleaned.strip("-")
    return cleaned or "patient"


def _save_upload(upload: UploadFile, target: Path) -> None:
    suffix = Path(upload.filename or "").suffix.lower() or ".jpg"
    final_path = target.with_suffix(suffix)
    with final_path.open("wb") as handle:
        shutil.copyfileobj(upload.file, handle)


def _run_url(run_id: str, relative: str) -> str:
    return f"/runs/{run_id}/{relative}".replace("\\", "/")


def _update_job(run_id: str, **kwargs) -> None:
    with _job_lock:
        if run_id in _job_store:
            _job_store[run_id].update(kwargs)


def _pipeline_worker(
    run_id: str,
    patient_id: str,
    image_map: Dict[Tuple[str, str], str],
    output_dir: Path,
    camera_calib: str,
    allow_borrowed_scale: bool,
    lenient_mode: bool,
) -> None:
    try:
        pipeline = FootPipeline(
            sam_path="checkpoints/sam_b.pt",
            card_model_path="checkpoints/card_detector.pt",
            coin_model_path="checkpoints/coin_detector.pt",
            landmark_configs=_default_landmark_configs(),
            camera_calib=(camera_calib or None),
            viz_dir=str(output_dir),
            allow_borrowed_scale=allow_borrowed_scale,
            lenient_mode=lenient_mode,
            seg_model_path="checkpoints/unet_mobilenet_v2_best.pt",
        )

        def _on_progress(info: dict) -> None:
            _update_job(run_id,
                        percent=info.get("percent", 0),
                        stage=info.get("stage", ""),
                        view=info.get("view"))

        # Sanitize patient_id for use in file paths.
        # Raw patient_id may contain "/" (e.g. "014/2025") which breaks
        # Path concatenation and creates phantom subdirectories.
        safe_patient_id = _slugify(patient_id)

        start_time = time.time()
        # Read demographics from patient_info.json so the pipeline can
        # apply demographic-aware sanity widening + skip toe_axis_angle
        # for amputated patients. Only the relevant subset is passed.
        _patient_info_for_pipeline = {}
        _meta_path_pre = output_dir.parent / "patient_info.json"
        try:
            _meta_pre = (
                json.loads(_meta_path_pre.read_text(encoding="utf-8"))
                if _meta_path_pre.exists() else {}
            )
            _patient_info_for_pipeline = {
                "diabetes":       _meta_pre.get("diabetes", ""),
                "amputated_toes": _meta_pre.get("amputated_toes", ""),
                "who_grade":      _meta_pre.get("who_grade", ""),
            }
        except Exception:
            _patient_info_for_pipeline = {}

        result = pipeline.run(
            patient_id=safe_patient_id,
            images=image_map,
            progress_callback=_on_progress,
            patient_info=_patient_info_for_pipeline,
        )
        duration_secs = round(time.time() - start_time, 1)

        # Save duration to patient_info.json. Always initialize meta to a
        # dict so the payload assembly below never hits NameError when the
        # file is absent (e.g. concurrent delete, fresh run race).
        meta = {}
        run_dir = output_dir.parent
        meta_path = run_dir / "patient_info.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                meta["duration_secs"] = duration_secs
                meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            except Exception:
                pass

        compact = result.to_dict()
        full    = result.to_dict_full()
        compact_path = output_dir / f"{safe_patient_id}_measurements.json"
        full_path    = output_dir / f"{safe_patient_id}_measurements_full.json"
        compact_path.write_text(json.dumps(compact, indent=2), encoding="utf-8")
        full_path.write_text(json.dumps(full, indent=2), encoding="utf-8")

        # Save patient data + measurements to Firestore
        cloud_storage.save_run_to_firestore(
            run_id=run_id,
            patient_meta=meta,
            compact=compact,
            full=full,
            overall_quality=result.overall_quality,
            duration_secs=duration_secs,
        )

        # Collect visualization image URLs
        viz_images = {"seg": {}, "lm": {}}
        for side in ("left", "right"):
            for view in ("plantar", "dorsal", "medial"):
                for suffix, bucket in [("seg", "seg"), ("lm", "lm")]:
                    fname = f"{patient_id}_{side}_{view}_{suffix}.jpg"
                    fpath = output_dir / fname
                    if fpath.exists():
                        viz_images[bucket][f"{side}_{view}"] = _run_url(run_id, f"output/{fname}")

        # Upload viz images to Cloudinary and update Firestore URLs
        viz_local_paths = {}
        for side in ("left", "right"):
            for view in ("plantar", "dorsal", "medial"):
                for suffix in ("seg", "lm", "viz"):
                    fname = f"{patient_id}_{side}_{view}_{suffix}.jpg"
                    fpath = output_dir / fname
                    if fpath.exists():
                        viz_local_paths[f"{side}_{view}_{suffix}"] = str(fpath)

        cld_seg: dict = {}
        cld_lm:  dict = {}
        cld_viz: dict = {}
        if viz_local_paths:
            all_urls = cloud_storage.upload_viz_images_to_storage(run_id, viz_local_paths)
            cld_seg = {k[:-4]: u for k, u in all_urls.items() if k.endswith("_seg")}
            cld_lm  = {k[:-3]: u for k, u in all_urls.items() if k.endswith("_lm")}
            cld_viz = {k[:-4]: u for k, u in all_urls.items() if k.endswith("_viz")}
            cloud_storage.update_run_storage_urls(
                run_id,
                storage_input={},
                storage_seg=cld_seg,
                storage_lm=cld_lm,
                storage_viz=cld_viz,
            )

        payload = {
            "patient_id": patient_id,
            "quality": result.overall_quality,
            "run_id": run_id,
            "compact_json_url": _run_url(run_id, f"output/{compact_path.name}"),
            "full_json_url":    _run_url(run_id, f"output/{full_path.name}"),
            "result":           full,
            "viz_seg": viz_images["seg"],
            "viz_lm": viz_images["lm"],
            # Include patient_info so the SPA technician table can fall back
            # to manual measurements when AI values are rejected.
            "patient_info":     meta,
        }
        payload["run_url"] = payload["full_json_url"]
        payload["duration_secs"] = duration_secs
        payload["cloudinary_seg"] = cld_seg
        payload["cloudinary_lm"]  = cld_lm

        _update_job(run_id, status="complete", percent=100, payload=payload)

    except Exception as exc:
        tb = traceback.format_exc()
        log.error("Pipeline failed for run %s: %s\n%s", run_id, exc, tb)
        cloud_storage.log_error(run_id, str(exc), tb)
        _update_job(run_id, status="error", error=str(exc))
    finally:
        PIPELINE_LOCK.release()


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────

@app.post("/api/login")
@limiter.limit("5/minute")
def api_login(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
) -> JSONResponse:
    user = cloud_storage.get_user_from_firestore(username)
    if user is None:
        users = _load_users()
        user = users.get(username)
    if user and "password" in user and "password_hash" not in user:
        user["password_hash"] = user["password"]
    if not user or not _verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    if not user.get("approved", False):
        raise HTTPException(status_code=403, detail="Your account is pending admin approval.")
    token = uuid4().hex
    expires_at = (datetime.now() + timedelta(hours=8)).isoformat()
    session_data = {
        "username":   username,
        "role":       user["role"],
        "name":       user.get("name", username),
        "center":     user.get("center", ""),
        "created_at": datetime.now().isoformat(),
        "expires_at": expires_at,
    }
    _sessions[token] = session_data
    cloud_storage.save_session(token, session_data)
    must_change = user.get("must_change_password", False)
    resp = JSONResponse({"ok": True, "role": user["role"], "must_change_password": must_change})
    resp.set_cookie(key="session", value=token, httponly=True, samesite="lax")
    return resp


@app.post("/api/signup")
def api_signup(
    username: str = Form(...),
    password: str = Form(...),
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    state: str = Form(""),
    center: str = Form(""),
) -> JSONResponse:
    if not username.strip() or not password.strip() or not name.strip():
        raise HTTPException(status_code=400, detail="Username, password, and name are required.")
    # Check duplicate — Firestore first, fallback to local
    existing = cloud_storage.get_user_from_firestore(username)
    if existing is None:
        existing = _load_users().get(username)
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists.")
    new_user = {
        "password_hash": _hash_password(password),
        "role": "agent",
        "name": name.strip(),
        "phone": phone.strip(),
        "email": email.strip(),
        "center": center.strip(),
        "state": state.strip(),
        "created_at": datetime.now().isoformat(),
        "approved": True,
    }
    cloud_storage.save_user_to_firestore(username, new_user)
    # Mirror to local file
    users = _load_users()
    users[username] = new_user
    with _users_lock:
        USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")
    return JSONResponse({"ok": True, "message": "Account created. You can now log in."})


@app.post("/api/logout")
def api_logout(request: Request) -> JSONResponse:
    token = request.cookies.get("session")
    if token:
        _sessions.pop(token, None)
        cloud_storage.delete_session(token)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(key="session")
    return resp


@app.post("/api/change-password")
def api_change_password(
    request: Request,
    old_password: str = Form(...),
    new_password: str = Form(...),
) -> JSONResponse:
    session = _get_session(request)
    if not session:
        raise HTTPException(status_code=401)
    if len(new_password.strip()) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters.")
    username = session["username"]
    user = cloud_storage.get_user_from_firestore(username)
    if user is None:
        user = _load_users().get(username)
    if not user or not _verify_password(old_password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")
    updated = {"password_hash": _hash_password(new_password), "must_change_password": False}
    cloud_storage.update_user_in_firestore(username, updated)
    users = _load_users()
    if username in users:
        users[username].update(updated)
        with _users_lock:
            USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")
    return JSONResponse({"ok": True})


@app.get("/api/me")
def api_me(request: Request) -> JSONResponse:
    session = _get_session(request)
    if not session:
        raise HTTPException(status_code=401)
    return JSONResponse({
        "username": session["username"],
        "role": session.get("role", "admin"),
        "name": session.get("name", session["username"]),
        "center": session.get("center", ""),
    })


@app.get("/api/agents")
def api_agents(request: Request) -> JSONResponse:
    session = _get_session(request)
    if not session or session.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    users = _load_users()
    agents = []
    for uname, u in users.items():
        if u.get("role") == "agent":
            agents.append({
                "username": uname,
                "name": u.get("name", ""),
                "phone": u.get("phone", ""),
                "email": u.get("email", ""),
                "center": u.get("center", ""),
                "state": u.get("state", ""),
                "approved": u.get("approved", False),
                "created_at": u.get("created_at", ""),
            })
    return JSONResponse(agents)


@app.post("/api/agents/{username}/approve")
def api_agent_approve(username: str, request: Request) -> JSONResponse:
    session = _get_session(request)
    if not session or session.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    user = cloud_storage.get_user_from_firestore(username)
    if user is None:
        user = _load_users().get(username)
    if not user or user.get("role") != "agent":
        raise HTTPException(status_code=404, detail="Agent not found.")
    cloud_storage.update_user_in_firestore(username, {"approved": True})
    # Mirror to local file
    users = _load_users()
    if username in users:
        users[username]["approved"] = True
        with _users_lock:
            USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")
    return JSONResponse({"ok": True})


@app.post("/api/agents/{username}/revoke")
def api_agent_revoke(username: str, request: Request) -> JSONResponse:
    session = _get_session(request)
    if not session or session.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    user = cloud_storage.get_user_from_firestore(username)
    if user is None:
        user = _load_users().get(username)
    if not user or user.get("role") != "agent":
        raise HTTPException(status_code=404, detail="Agent not found.")
    cloud_storage.update_user_in_firestore(username, {"approved": False})
    # Mirror to local file
    users = _load_users()
    if username in users:
        users[username]["approved"] = False
        with _users_lock:
            USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")
    return JSONResponse({"ok": True})


@app.post("/api/agents/{username}/reset-password")
def api_agent_reset_password(username: str, request: Request, new_password: str = Form(...)) -> JSONResponse:
    session = _get_session(request)
    if not session or session.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    if len(new_password.strip()) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    user = cloud_storage.get_user_from_firestore(username)
    if user is None:
        user = _load_users().get(username)
    if not user or user.get("role") != "agent":
        raise HTTPException(status_code=404, detail="Agent not found.")
    updated = {"password_hash": _hash_password(new_password), "must_change_password": True}
    cloud_storage.update_user_in_firestore(username, updated)
    users = _load_users()
    if username in users:
        users[username].update(updated)
        with _users_lock:
            USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")
    return JSONResponse({"ok": True})


_centers_cache: dict | None = None
_districts_cache: dict | None = None
_staff_cache: dict | None = None
_center_district_cache: dict | None = None
_center_state_cache: dict | None = None


def _load_lookup_caches() -> None:
    """Load centers.csv, districts.csv, and staff.csv into global caches (once)."""
    global _centers_cache, _districts_cache, _staff_cache, _center_district_cache, _center_state_cache
    base = Path(__file__).parent
    # --- Centers (from centers.csv) ---
    if _centers_cache is None:
        centers_path = base / "centers.csv"
        mapping: Dict[str, List[str]] = {}
        center_district: Dict[str, str] = {}
        center_state: Dict[str, str] = {}
        if centers_path.exists():
            with open(centers_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    state = row.get("State", "").strip()
                    district = row.get("District", "").strip()
                    center = row.get("Project / Center Name", "").strip()
                    if state and center:
                        label = f"{center} ({district})" if district else center
                        mapping.setdefault(state, []).append(label)
                        # The capture form submits the dropdown's value, which is
                        # this same display label (not the raw center name) — key
                        # by both so a run's stored capture_center resolves either
                        # way regardless of when/how it was captured.
                        center_state[center] = state
                        center_state[label] = state
                        if district:
                            center_district[center] = district
                            center_district[label] = district
        _centers_cache = mapping
        _center_district_cache = center_district
        _center_state_cache = center_state
    # --- Districts (from districts.csv — all India) ---
    if _districts_cache is None:
        dist_path = base / "districts.csv"
        dist_mapping: Dict[str, List[str]] = {}
        if dist_path.exists():
            with open(dist_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    state = row.get("State", "").strip()
                    district = row.get("District", "").strip()
                    if state and district:
                        dist_mapping.setdefault(state, []).append(district)
        _districts_cache = dist_mapping
    # --- Staff (from staff.csv) ---
    if _staff_cache is None:
        staff_path = base / "staff.csv"
        staff_map: Dict[str, List[str]] = {}
        if staff_path.exists():
            with open(staff_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    state = row.get("State", "").strip()
                    name = row.get("Name", "").strip()
                    if state and name:
                        staff_map.setdefault(state, []).append(name)
        _staff_cache = staff_map


@app.get("/api/centers")
def api_centers(request: Request) -> JSONResponse:
    if not _get_session(request):
        raise HTTPException(status_code=401)
    _load_lookup_caches()
    # States list comes from districts.csv (all 34 states/UTs)
    states = sorted((_districts_cache or {}).keys())
    return JSONResponse({"states": states, "centers": _centers_cache or {}, "districts": _districts_cache or {}, "staff": _staff_cache or {}})


@app.get("/api/signup-options")
def api_signup_options() -> JSONResponse:
    """Public (no auth) endpoint for the signup page — returns states and centers."""
    _load_lookup_caches()
    states = sorted((_districts_cache or {}).keys())
    return JSONResponse({"states": states, "centers": _centers_cache or {}})


@app.get("/api/stats")
def api_stats(request: Request) -> JSONResponse:
    session = _get_session(request)
    if not session:
        raise HTTPException(status_code=401)

    role = session.get("role", "admin")
    username = session.get("username", "")

    total = 0
    successful = 0
    recent_date = None
    total_duration = 0.0
    duration_count = 0

    if RUNS_DIR.exists():
        for run_dir in sorted(RUNS_DIR.iterdir(), reverse=True):
            if not run_dir.is_dir():
                continue

            # Read patient metadata
            meta_path = run_dir / "patient_info.json"
            meta = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

            # Agent filtering: only show own runs
            if role == "agent" and meta.get("submitted_by", "") != username:
                continue

            total += 1

            # Check for compact measurements JSON
            output_dir = run_dir / "output"
            compact_files = list(output_dir.glob("*_measurements.json")) if output_dir.exists() else []
            if compact_files:
                successful += 1

            # Get date from patient_info
            submitted = meta.get("submitted_at", "")
            if submitted and recent_date is None:
                recent_date = submitted[:10]

            # Accumulate inference duration
            dur = meta.get("duration_secs")
            if dur is not None:
                total_duration += float(dur)
                duration_count += 1

    avg_time = round(total_duration / duration_count, 1) if duration_count > 0 else None

    return JSONResponse({
        "total": total,
        "successful": successful,
        "recent_date": recent_date or "--",
        "avg_inference_secs": avg_time,
    })


@app.get("/api/dashboard")
def api_dashboard(request: Request) -> JSONResponse:
    """
    Admin-only aggregated stats for charts:
      by_month: {"2026-01": N, ...}
      by_center: {"Vijayawada": N, ...}
      by_gender: {"male": N, "female": N, ...}
    """
    session = _get_session(request)
    if not session:
        raise HTTPException(status_code=401)
    if session.get("role") != "admin":
        raise HTTPException(status_code=403)

    from collections import defaultdict
    by_month:  dict = defaultdict(int)
    by_center: dict = defaultdict(int)
    by_gender: dict = defaultdict(int)

    def _aggregate_run(meta: dict) -> None:
        submitted = meta.get("submitted_at", "")
        month = submitted[:7] if submitted else "unknown"
        by_month[month] += 1
        center = (meta.get("capture_center") or "unknown").strip() or "unknown"
        by_center[center] += 1
        gender = (meta.get("gender") or "unknown").strip().lower() or "unknown"
        by_gender[gender] += 1

    # Try Firestore first
    db = cloud_storage._get_db()
    if db:
        try:
            for doc in db.collection("runs").stream():
                _aggregate_run(doc.to_dict())
            return JSONResponse({
                "by_month":  dict(by_month),
                "by_center": dict(by_center),
                "by_gender": dict(by_gender),
            })
        except Exception as exc:
            log.warning("api_dashboard Firestore error: %s", exc)

    # Local scan fallback
    if RUNS_DIR.exists():
        for run_dir in RUNS_DIR.iterdir():
            if not run_dir.is_dir():
                continue
            meta: dict = {}
            meta_path = run_dir / "patient_info.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            _aggregate_run(meta)

    return JSONResponse({
        "by_month":  dict(by_month),
        "by_center": dict(by_center),
        "by_gender": dict(by_gender),
    })


@app.get("/api/dashboard/drilldown")
def api_dashboard_drilldown(
    request: Request,
    date_from: str = "",
    date_to: str = "",
) -> JSONResponse:
    """
    Admin-only State -> District -> User drill-down aggregation, plus a
    cumulative summary block for the overview popup.

    Query params:
      date_from, date_to : "YYYY-MM-DD" strings, inclusive, filtered against
                            submitted_at (compared as date-prefix strings, same
                            convention as filterDashboard()'s client-side by_month
                            filter — no timezone conversion, matches existing
                            date-range semantics used elsewhere in this file).

    Response shape:
      {
        "summary": {
          "total_patients": N, "total_measurements": N,
          "completion_rate_pct": F, "date_from": "...", "date_to": "..."
        },
        "tree": {
          "<State>": {
            "count": N,
            "districts": {
              "<District>": {
                "count": N,
                "users": { "<submitted_by>": N, ... }
              }, ...
            }
          }, ...
        },
        "users": ["<submitted_by>", ...]   // distinct users present, for the filter dropdown
      }
    """
    session = _get_session(request)
    if not session:
        raise HTTPException(status_code=401)
    if session.get("role") != "admin":
        raise HTTPException(status_code=403)

    _load_lookup_caches()
    from collections import defaultdict

    tree: dict = {}
    users_seen: set = set()
    total_patients = 0
    total_measurements = 0

    def _resolve_state(meta: dict) -> str:
        state = (meta.get("state") or "").strip()
        if state:
            return state
        center = (meta.get("capture_center") or "").strip()
        return (_center_state_cache or {}).get(center, "") or "Unknown"

    def _resolve_district(meta: dict) -> str:
        district = (meta.get("district") or "").strip()
        if district:
            return district
        center = (meta.get("capture_center") or "").strip()
        return (_center_district_cache or {}).get(center, "") or "Unknown"

    def _in_range(submitted_at: str) -> bool:
        d = (submitted_at or "")[:10]
        if date_from and (not d or d < date_from):
            return False
        if date_to and (not d or d > date_to):
            return False
        return True

    def _aggregate(meta: dict, measurements_present: bool) -> None:
        nonlocal total_patients, total_measurements
        submitted_at = meta.get("submitted_at", "")
        if not _in_range(submitted_at):
            return
        state = _resolve_state(meta)
        district = _resolve_district(meta)
        user = (meta.get("submitted_by") or "").strip() or "Unknown"

        total_patients += 1
        if measurements_present:
            total_measurements += 1
        users_seen.add(user)

        st = tree.setdefault(state, {"count": 0, "districts": {}})
        st["count"] += 1
        ds = st["districts"].setdefault(district, {"count": 0, "users": defaultdict(int)})
        ds["count"] += 1
        ds["users"][user] += 1

    # Try Firestore first
    db = cloud_storage._get_db()
    used_firestore = False
    if db:
        try:
            for doc in db.collection("runs").stream():
                d = doc.to_dict()
                _aggregate(d, bool(d.get("measurements_compact")))
            used_firestore = True
        except Exception as exc:
            log.warning("api_dashboard_drilldown Firestore error: %s", exc)

    # Local scan fallback
    if not used_firestore and RUNS_DIR.exists():
        for run_dir in RUNS_DIR.iterdir():
            if not run_dir.is_dir():
                continue
            meta: dict = {}
            meta_path = run_dir / "patient_info.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            has_meas = (run_dir / "output").exists() and any(
                (run_dir / "output").glob("*_measurements.json")
            )
            _aggregate(meta, has_meas)

    # Convert nested defaultdicts to plain dicts for JSON serialisation
    for st in tree.values():
        for ds in st["districts"].values():
            ds["users"] = dict(ds["users"])

    completion_rate = round(100.0 * total_measurements / total_patients, 1) if total_patients else 0.0

    return JSONResponse({
        "summary": {
            "total_patients": total_patients,
            "total_measurements": total_measurements,
            "completion_rate_pct": completion_rate,
            "date_from": date_from or None,
            "date_to": date_to or None,
        },
        "tree": tree,
        "users": sorted(users_seen),
    })


@app.get("/api/export/csv")
def api_export_csv(request: Request) -> StreamingResponse:
    session = _get_session(request)
    if not session:
        raise HTTPException(status_code=401)

    role     = session.get("role", "agent")
    username = session.get("username", "")

    import io
    CSV_FIELDS = [
        "run_id", "patient_id", "patient_name", "age", "gender", "exam_date",
        "district", "village", "capture_center", "submitted_by", "submitted_at",
        "duration_secs",
        "foot_length_left_cm", "foot_length_right_cm",
        "forefoot_width_left_cm", "forefoot_width_right_cm",
        "heel_width_left_cm", "heel_width_right_cm",
        "diabetes", "amputated_toes", "disease_type", "who_grade", "phone",
    ]

    def _mval(measurements, side, key):
        v = measurements.get(side, {}).get(key, {})
        if isinstance(v, dict):
            mm = v.get("value_mm", "")
            return f"{mm / 10:.2f}" if isinstance(mm, (int, float)) else ""
        return v if v else ""

    def _generate():
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        yield output.getvalue()

        # Collect runs from Firestore or local scan
        all_runs = []
        fs_runs = cloud_storage.get_all_runs_from_firestore(role, username)
        if fs_runs is not None:
            # Fetch full Firestore docs for measurements
            db = cloud_storage._get_db()
            if db:
                q = db.collection("runs").order_by("created_at", direction="DESCENDING")
                if role == "agent":
                    q = q.where("submitted_by", "==", username)
                for doc in q.stream():
                    all_runs.append(doc.to_dict())
        else:
            # Local scan fallback
            if RUNS_DIR.exists():
                for run_dir in sorted(RUNS_DIR.iterdir(), reverse=True):
                    if not run_dir.is_dir():
                        continue
                    meta_path = run_dir / "patient_info.json"
                    meta = {}
                    if meta_path.exists():
                        try:
                            meta = json.loads(meta_path.read_text(encoding="utf-8"))
                        except Exception:
                            pass
                    measurements = {}
                    for f in (run_dir / "output").glob("*_measurements.json") if (run_dir / "output").exists() else []:
                        try:
                            measurements = json.loads(f.read_text(encoding="utf-8"))
                        except Exception:
                            pass
                    meta["run_id"] = run_dir.name
                    meta["measurements_compact"] = measurements
                    if role == "agent" and meta.get("submitted_by", "") != username:
                        continue
                    all_runs.append(meta)

        for run in all_runs:
            m = run.get("measurements_compact", {})
            row = {
                "run_id":                  run.get("run_id", ""),
                "patient_id":              run.get("patient_id", ""),
                "patient_name":            run.get("patient_name", ""),
                "age":                     run.get("age", ""),
                "gender":                  run.get("gender", ""),
                "exam_date":               run.get("exam_date", ""),
                "district":                run.get("district", ""),
                "village":                 run.get("village", ""),
                "capture_center":          run.get("capture_center", ""),
                "submitted_by":            run.get("submitted_by", ""),
                "submitted_at":            run.get("submitted_at", ""),
                "duration_secs":           run.get("duration_secs", ""),
                "foot_length_left_cm":     _mval(m, "left",  "foot_length_mm"),
                "foot_length_right_cm":    _mval(m, "right", "foot_length_mm"),
                "forefoot_width_left_cm":  _mval(m, "left",  "forefoot_width_mm"),
                "forefoot_width_right_cm": _mval(m, "right", "forefoot_width_mm"),
                "heel_width_left_cm":      _mval(m, "left",  "heel_width_mm"),
                "heel_width_right_cm":     _mval(m, "right", "heel_width_mm"),
                "diabetes":                run.get("diabetes", ""),
                "amputated_toes":          run.get("amputated_toes", ""),
                "disease_type":            run.get("disease_type", ""),
                "who_grade":               run.get("who_grade", ""),
                "phone":                   run.get("phone", ""),
            }
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writerow(row)
            yield output.getvalue()

    suffix = username if role == "agent" else "all"
    filename = f"lepra_patients_{suffix}_{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        _generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.post("/api/runs/{run_id}/edit")
def api_edit_run(
    run_id: str,
    request: Request,
    patient_name:     str = Form(""),
    age:              str = Form(""),
    gender:           str = Form(""),
    diabetes:         str = Form(""),
    amputated_toes:   str = Form(""),
    disease_type:     str = Form(""),
    who_grade:        str = Form(""),
    state:            str = Form(""),
    district:         str = Form(""),
    village:          str = Form(""),
    capture_center:   str = Form(""),
    referring_doctor: str = Form(""),
    exam_date:        str = Form(""),
    clinical_notes:   str = Form(""),
    phone:            str = Form(""),
) -> JSONResponse:
    """Update editable patient demographics for an existing run (no re-inference)."""
    session = _get_session(request)
    if not session:
        raise HTTPException(status_code=401)

    run_dir = RUNS_DIR / run_id
    if not run_dir.is_dir():
        raise HTTPException(status_code=404, detail="Run not found.")

    meta_path = run_dir / "patient_info.json"
    meta: dict = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Only admin or the submitter can edit
    if session.get("role") != "admin" and meta.get("submitted_by", "") != session.get("username", ""):
        raise HTTPException(status_code=403, detail="Not allowed to edit this run.")

    editable = {
        "patient_name":     patient_name.strip(),
        "age":              age.strip(),
        "gender":           gender.strip(),
        "diabetes":         diabetes.strip(),
        "amputated_toes":   amputated_toes.strip(),
        "disease_type":     disease_type.strip(),
        "who_grade":        who_grade.strip(),
        "state":            state.strip(),
        "district":         district.strip(),
        "village":          village.strip(),
        "capture_center":   capture_center.strip(),
        "referring_doctor": referring_doctor.strip(),
        "exam_date":        exam_date.strip(),
        "clinical_notes":   clinical_notes.strip(),
        "phone":            phone.strip(),
    }
    meta.update(editable)

    # Save to disk
    try:
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save: {exc}") from exc

    # Mirror to Firestore
    cloud_storage.update_user_in_firestore  # (reuse pattern via direct call below)
    db = cloud_storage._get_db()
    if db:
        try:
            db.collection("runs").document(run_id).set(editable, merge=True)
        except Exception:
            pass

    log.info("Run %s demographics edited by %s", run_id, session.get("username"))
    return JSONResponse({"ok": True})


@app.get("/api/runs/{run_id}/meta")
def api_get_run_meta(run_id: str, request: Request) -> JSONResponse:
    """Return editable patient demographics for pre-filling the edit modal."""
    session = _get_session(request)
    if not session:
        raise HTTPException(status_code=401)

    run_dir = RUNS_DIR / run_id
    if not run_dir.is_dir():
        # Try Firestore
        db = cloud_storage._get_db()
        if db:
            try:
                doc = db.collection("runs").document(run_id).get()
                if doc.exists:
                    d = doc.to_dict()
                    if session.get("role") != "admin" and d.get("submitted_by", "") != session.get("username", ""):
                        raise HTTPException(status_code=403)
                    return JSONResponse({k: d.get(k, "") for k in [
                        "patient_name", "age", "gender", "diabetes", "amputated_toes",
                        "disease_type", "who_grade", "district", "village", "capture_center",
                        "referring_doctor", "exam_date", "clinical_notes", "phone",
                    ]})
            except HTTPException:
                raise
            except Exception:
                pass
        raise HTTPException(status_code=404, detail="Run not found.")

    meta_path = run_dir / "patient_info.json"
    meta: dict = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    if session.get("role") != "admin" and meta.get("submitted_by", "") != session.get("username", ""):
        raise HTTPException(status_code=403)

    return JSONResponse({k: meta.get(k, "") for k in [
        "patient_name", "age", "gender", "diabetes", "amputated_toes",
        "disease_type", "who_grade", "district", "village", "capture_center",
        "referring_doctor", "exam_date", "clinical_notes", "phone",
    ]})


@app.get("/api/history")
def api_history(request: Request) -> JSONResponse:
    session = _get_session(request)
    if not session:
        raise HTTPException(status_code=401)

    role = session.get("role", "admin")
    username = session.get("username", "")

    # Prefer Firestore when available
    firebase_runs = cloud_storage.get_all_runs_from_firestore(role, username)
    if firebase_runs is not None:
        return JSONResponse(firebase_runs)

    # Fallback: local directory scan
    runs = []
    if RUNS_DIR.exists():
        for run_dir in sorted(RUNS_DIR.iterdir(), reverse=True):
            if not run_dir.is_dir():
                continue
            run_id = run_dir.name
            entry = {"run_id": run_id, "patient_id": "", "patient_name": "", "date": "", "quality": "unknown", "foot_length_left": "--", "foot_length_right": "--", "json_url": "", "submitted_by": ""}

            # Read patient metadata
            meta_path = run_dir / "patient_info.json"
            meta = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    entry["patient_id"] = meta.get("patient_id", "")
                    entry["patient_name"] = meta.get("patient_name", "")
                    entry["submitted_by"] = meta.get("submitted_by", "")
                    submitted = meta.get("submitted_at", "")
                    if submitted:
                        entry["date"] = submitted[:10]
                except Exception:
                    pass

            # Agent filtering: only show own runs
            if role == "agent" and meta.get("submitted_by", "") != username:
                continue

            # Read compact measurements
            output_dir = run_dir / "output"
            compact_files = list(output_dir.glob("*_measurements.json")) if output_dir.exists() else []
            if compact_files:
                entry["json_url"] = f"/runs/{run_id}/output/{compact_files[0].name}"
                try:
                    data = json.loads(compact_files[0].read_text(encoding="utf-8"))
                    entry["quality"] = data.get("overall_quality", "unknown")
                    left = data.get("left", {})
                    right = data.get("right", {})
                    fl = left.get("foot_length_mm", {})
                    fr = right.get("foot_length_mm", {})
                    if isinstance(fl, dict) and fl.get("value_mm"):
                        entry["foot_length_left"] = f"{fl['value_mm'] / 10:.2f} cm"
                    if isinstance(fr, dict) and fr.get("value_mm"):
                        entry["foot_length_right"] = f"{fr['value_mm'] / 10:.2f} cm"
                except Exception:
                    pass

            runs.append(entry)

    return JSONResponse(runs)


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    session = _get_session(request)
    if session:
        return HTMLResponse(HTML_APP)
    return HTMLResponse(_with_base(HTML_LOGIN))


@app.get("/signup", response_class=HTMLResponse)
def signup_page() -> HTMLResponse:
    return HTMLResponse(_with_base(HTML_SIGNUP))


@app.get("/health")
def health() -> dict:
    pipeline_free = PIPELINE_LOCK.acquire(blocking=False)
    if pipeline_free:
        PIPELINE_LOCK.release()
    return {
        "status":        "ok",
        "version":       "2.0.0",
        "firebase":      cloud_storage.firestore_available(),
        "pipeline_busy": not pipeline_free,
    }


@app.post("/api/validate-view")
async def api_validate_view(
    request: Request,
    image: UploadFile = File(...),
) -> JSONResponse:
    """
    Validate a single uploaded foot image.
    Auto-detects view type (plantar/dorsal/medial) only — no left/right.
    Left/right is resolved by the user via the pairing dialog in the UI.
    """
    session = _get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    try:
        seg_model = _get_validate_seg_model()
        card_model = _get_validate_card_model()
        if seg_model is None or card_model is None:
            # Models couldn't load — let the user proceed without strict validation
            return JSONResponse({
                "detected_view": None,
                "confidence": 0.0,
                "card_detected": False,
                "card_placement_ok": False,
                "card_conf": 0.0,
                "match_score": 0.0,
                "low_confidence": True,
                "issues": [],
                "error": "validation_unavailable",
            })
        image_bytes = await image.read()
        import foot_pipeline as _fp
        result = _fp.validate_image_view(
            image_bytes,
            seg_model=seg_model,
            card_model_path="checkpoints/card_detector.pt",
            yolo_model=card_model,
            samples_dir=str(SAMPLES_DIR),
        )
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({
            "detected_view": None,
            "confidence": 0.0,
            "card_detected": False,
            "card_placement_ok": False,
            "card_conf": 0.0,
            "match_score": 0.0,
            "low_confidence": True,
            "error": str(e),
        }, status_code=200)


@app.post("/predict", status_code=202)
def predict(
    request: Request,
    patient_id: str = Form(...),
    patient_name: str = Form(""),
    age: str = Form(""),
    gender: str = Form(""),
    diabetes: str = Form("no"),
    amputated_toes: str = Form("no"),
    abha_id: str = Form(""),
    aadhar_id: str = Form(""),
    disease_type: str = Form("leprosy"),
    who_grade: str = Form(""),
    state: str = Form(""),
    district: str = Form(""),
    village: str = Form(""),
    capture_center: str = Form(""),
    referring_doctor: str = Form(""),
    exam_date: str = Form(""),
    clinical_notes: str = Form(""),
    phone: str = Form(""),
    captured_by: str = Form(""),
    captured_by_other: str = Form(""),
    manual_foot_length_left: str = Form(""),
    manual_foot_length_right: str = Form(""),
    manual_ball_girth_left: str = Form(""),
    manual_ball_girth_right: str = Form(""),
    manual_instep_girth_left: str = Form(""),
    manual_instep_girth_right: str = Form(""),
    manual_malleoli_height_left: str = Form(""),
    manual_malleoli_height_right: str = Form(""),
    reference_type: str = Form("card"),
    camera_calib: str = Form(""),
    allow_borrowed_scale: bool = Form(True),
    lenient_mode: bool = Form(True),
    left_plantar:  UploadFile = File(...),
    left_dorsal:   UploadFile = File(...),
    left_medial:   UploadFile = File(...),
    right_plantar: UploadFile = File(...),
    right_dorsal:  UploadFile = File(...),
    right_medial:  UploadFile = File(...),
) -> JSONResponse:
    session = _get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    uploads = {
        "left_plantar":  left_plantar,
        "left_dorsal":   left_dorsal,
        "left_medial":   left_medial,
        "right_plantar": right_plantar,
        "right_dorsal":  right_dorsal,
        "right_medial":  right_medial,
    }
    missing = [name for name, upload in uploads.items() if not (upload.filename or "").strip()]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing uploads: {', '.join(missing)}")

    if not PIPELINE_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Service is busy. Try again after the current run finishes.")

    # CRITICAL: From here until thread.start(), any uncaught exception leaks the lock.
    # The try/except below ensures the lock is released on any failure path.
    _thread_started = False
    run_id    = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{_slugify(patient_id)}-{uuid4().hex[:6]}"
    run_dir   = RUNS_DIR / run_id
    input_dir = run_dir / "input"
    output_dir = run_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        image_map: Dict[Tuple[str, str], str] = {}
        for side, view in VIEW_FIELDS:
            key    = f"{side}_{view}"
            target = input_dir / key
            _save_upload(uploads[key], target)
            saved  = next(input_dir.glob(f"{key}.*"))
            image_map[(side, view)] = str(saved)
    except Exception as exc:
        PIPELINE_LOCK.release()
        for upload in uploads.values():
            upload.file.close()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        for upload in uploads.values():
            upload.file.close()

    # NOTE: Any failure between here and thread.start() must release PIPELINE_LOCK.
    # Save patient metadata (does not affect pipeline inference)
    patient_meta = {
        "patient_id": patient_id,
        "patient_name": patient_name.strip(),
        "age": age.strip(),
        "gender": gender.strip(),
        "diabetes": diabetes.strip(),
        "amputated_toes": amputated_toes.strip(),
        "abha_id": abha_id.strip(),
        "aadhar_id": aadhar_id.strip(),
        "disease_type": disease_type.strip(),
        "who_grade": who_grade.strip(),
        "state": state.strip(),
        "district": district.strip(),
        "village": village.strip(),
        "capture_center": capture_center.strip(),
        "referring_doctor": referring_doctor.strip(),
        "exam_date": exam_date.strip(),
        "clinical_notes": clinical_notes.strip(),
        "phone": phone.strip(),
        "captured_by": captured_by.strip() if captured_by != "__other__" else captured_by_other.strip(),
        "manual_measurements": {
            "foot_length":     {"left": manual_foot_length_left,     "right": manual_foot_length_right},
            "ball_girth":      {"left": manual_ball_girth_left,      "right": manual_ball_girth_right},
            "instep_girth":    {"left": manual_instep_girth_left,    "right": manual_instep_girth_right},
            "malleoli_height": {"left": manual_malleoli_height_left, "right": manual_malleoli_height_right},
        },
        "reference_type": reference_type.strip(),
        "submitted_by": session.get("username", ""),
        "submitted_by_role": session.get("role", ""),
        "submitted_at": datetime.now().isoformat(),
    }
    try:
        meta_path = run_dir / "patient_info.json"
        meta_path.write_text(json.dumps(patient_meta, indent=2), encoding="utf-8")

        # Upload input images to Firebase Storage in background (non-blocking)
        def _upload_inputs_bg(_run_id=run_id, _input_dir=input_dir):
            try:
                img_paths = {
                    f"{s}_{v}": str(next(_input_dir.glob(f"{s}_{v}.*"), ""))
                    for s, v in VIEW_FIELDS
                }
                img_paths = {k: p for k, p in img_paths.items() if p}
                urls = cloud_storage.upload_input_images_to_storage(_run_id, img_paths)
                if urls:
                    cloud_storage.update_run_storage_urls(
                        _run_id,
                        storage_input=urls,
                        storage_seg={},
                        storage_lm={},
                        storage_viz={},
                    )
            except Exception as up_exc:
                log.warning("Background input upload failed for %s: %s", _run_id, up_exc)
        threading.Thread(target=_upload_inputs_bg, daemon=True).start()

        with _job_lock:
            _job_store[run_id] = {
                "status":  "processing",
                "percent": 0,
                "stage":   "preprocessing",
                "view":    None,
                "payload": None,
                "error":   None,
            }
    except Exception as exc:
        PIPELINE_LOCK.release()
        raise HTTPException(status_code=500, detail=f"Failed to prepare pipeline: {exc}") from exc

    try:
        thread = threading.Thread(
            target=_pipeline_worker,
            kwargs=dict(
                run_id=run_id,
                patient_id=patient_id,
                image_map=image_map,
                output_dir=output_dir,
                camera_calib=camera_calib.strip(),
                allow_borrowed_scale=bool(allow_borrowed_scale),
                lenient_mode=bool(lenient_mode),
            ),
            daemon=True,
        )
        thread.start()
        _thread_started = True
    except Exception as exc:
        # If thread fails to start, release the lock so app stays usable
        PIPELINE_LOCK.release()
        raise HTTPException(status_code=500, detail=f"Failed to start pipeline: {exc}") from exc

    if not _thread_started:
        # Defensive — shouldn't happen, but ensure lock is released
        PIPELINE_LOCK.release()

    # Duplicate detection — warn if same patient_id + exam_date already exists
    duplicate_run_id = None
    try:
        db = cloud_storage._get_db()
        if db and exam_date.strip():
            for doc in db.collection("runs")\
                    .where("patient_id", "==", patient_id)\
                    .where("exam_date", "==", exam_date.strip())\
                    .limit(2).stream():
                if doc.id != run_id:
                    duplicate_run_id = doc.id
                    break
    except Exception:
        pass

    return JSONResponse({"run_id": run_id, "status": "processing", "duplicate_warning": duplicate_run_id}, status_code=202)


@app.get("/progress/{run_id}")
def progress_stream(run_id: str, request: Request) -> StreamingResponse:
    if not _get_session(request):
        raise HTTPException(status_code=401, detail="Not authenticated.")
    if run_id not in _job_store:
        raise HTTPException(status_code=404, detail="Unknown run_id.")

    def _event_generator():
        while True:
            with _job_lock:
                job = dict(_job_store.get(run_id, {}))

            if not job:
                break

            if job["status"] == "complete":
                data = json.dumps({"status": "complete", "payload": job["payload"]})
                yield f"data: {data}\n\n"
                break
            elif job["status"] == "error":
                data = json.dumps({"status": "error", "error": job.get("error", "Unknown error")})
                yield f"data: {data}\n\n"
                break
            else:
                data = json.dumps({
                    "status":  "processing",
                    "percent": job.get("percent", 0),
                    "stage":   job.get("stage", ""),
                    "view":    job.get("view"),
                })
                yield f"data: {data}\n\n"

            time.sleep(0.4)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/result/{run_id}")
def get_result(run_id: str, request: Request) -> JSONResponse:
    if not _get_session(request):
        raise HTTPException(status_code=401, detail="Not authenticated.")
    with _job_lock:
        job = dict(_job_store.get(run_id, {}))
    if not job:
        raise HTTPException(status_code=404, detail="Unknown run_id.")
    if job["status"] == "processing":
        raise HTTPException(status_code=202, detail="Job still running.")
    if job["status"] == "error":
        raise HTTPException(status_code=500, detail=job.get("error", "Pipeline error."))
    return JSONResponse(job["payload"])


@app.get("/report/{run_id}", response_class=HTMLResponse)
def report_page(run_id: str, request: Request):
    """Printable report page — user can Ctrl+P / Print to PDF."""
    if not _get_session(request):
        raise HTTPException(status_code=401, detail="Not authenticated.")

    run_dir = RUNS_DIR / run_id
    output_dir = run_dir / "output"
    meta = {}
    full_json = None
    fs_doc = None

    # Try local files first
    if run_dir.exists():
        meta_path = run_dir / "patient_info.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        for f in output_dir.glob("*_measurements_full.json"):
            full_json = json.loads(f.read_text(encoding="utf-8"))
            break

    # Fallback to Firestore
    if not full_json:
        fs_doc = cloud_storage.get_run_from_firestore(run_id)
        if fs_doc:
            meta = {k: fs_doc.get(k, "") for k in [
                "patient_id", "patient_name", "age", "gender", "exam_date",
                "state", "district", "village", "capture_center",
                "submitted_by", "submitted_at",
                "diabetes", "amputated_toes", "disease_type", "who_grade",
                "phone", "abha_id", "aadhar_id",
                "referring_doctor", "captured_by",
                "clinical_notes", "reference_type",
            ]}
            full_str = fs_doc.get("measurements_full_json", "")
            if full_str:
                full_json = json.loads(full_str) if isinstance(full_str, str) else full_str

    if not full_json:
        raise HTTPException(status_code=404, detail="Results not found for this run.")

    patient_id = meta.get("patient_id", run_id)
    quality = full_json.get("overall_quality", "unknown")

    # Build measurements table rows
    LABELS = {
        "foot_length_mm": "Foot Length",
        "forefoot_width_mm": "Forefoot Width",
        "heel_width_mm": "Heel Width",
        "midfoot_width_mm": "Midfoot Width",
        "toe_axis_angle_deg": "Toe Axis Angle",
        "ball_girth_mm_provisional": "Ball Girth (est.)",
        "instep_girth_mm_provisional": "Instep Girth (est.)",
        "malleoli_height_mm": "Malleoli Height",
    }
    UNITS = {
        "foot_length_mm": "cm", "forefoot_width_mm": "cm",
        "heel_width_mm": "cm", "midfoot_width_mm": "cm",
        "toe_axis_angle_deg": "\u00b0",
        "ball_girth_mm_provisional": "cm",
        "instep_girth_mm_provisional": "cm",
        "malleoli_height_mm": "cm",
    }
    meas_rows = ""
    left_data = full_json.get("left", {})
    right_data = full_json.get("right", {})
    # Implausible measurements (sanity-gate rejections) render as em-dash.
    # The per-row badge + summary panel were removed: upload-time validate-
    # view modal is the user-facing QC checkpoint, and post-hoc rejection
    # text is not actionable in the PDF.

    def _fmt_meas(entry, unit):
        if not entry or not isinstance(entry, dict):
            return "\u2014"
        v = entry.get("value_mm")
        if v is None:
            return "\u2014"
        try:
            v = float(v)
        except (TypeError, ValueError):
            return "\u2014"
        if unit == "cm":
            return f'{v / 10:.2f} {unit}'
        return f'{v:.1f} {unit}'

    for key, label in LABELS.items():
        unit = UNITS.get(key, "cm")
        l_str = _fmt_meas(left_data.get(key, {}), unit)
        r_str = _fmt_meas(right_data.get(key, {}), unit)
        meas_rows += f"<tr><td>{label}</td><td style='text-align:right'>{l_str}</td><td style='text-align:right'>{r_str}</td></tr>"

    # Cross-foot sanity check warning (skip if either side dropped by sanity gate)
    l_len_obj = left_data.get("foot_length_mm", {}) or {}
    r_len_obj = right_data.get("foot_length_mm", {}) or {}
    l_len_val = l_len_obj.get("value_mm")
    r_len_val = r_len_obj.get("value_mm")
    try:
        l_len_val = float(l_len_val) if l_len_val is not None else 0
        r_len_val = float(r_len_val) if r_len_val is not None else 0
    except (TypeError, ValueError):
        l_len_val, r_len_val = 0, 0
    cross_foot_warning = ""
    if l_len_val > 0 and r_len_val > 0:
        ratio = r_len_val / l_len_val
        if ratio > 1.25 or ratio < 0.75:
            suspect = "Right" if ratio > 1.25 else "Left"
            cross_foot_warning = (
                f'<div style="background:#fef3c7;border:1px solid #f59e0b;border-radius:8px;padding:10px 14px;margin:12px 0;font-size:0.88rem;color:var(--warn-text);">'
                f'<strong>&#9888; Warning:</strong> Significant left-right difference detected '
                f'(L: {l_len_val/10:.1f} cm, R: {r_len_val/10:.1f} cm). '
                f'{suspect} foot measurements may be unreliable due to scale detection issues.</div>'
            )

    # Patient info rows
    dash = "\u2014"
    pid = meta.get("patient_id", "")
    pname = meta.get("patient_name", "")
    page = meta.get("age", "")
    pgender = meta.get("gender", "").title()
    pabha = meta.get("abha_id", "") or dash
    paadhar = meta.get("aadhar_id", "") or dash
    pdiab = meta.get("diabetes", "no").title()
    pamput = meta.get("amputated_toes", "no").title()
    pdisease = meta.get("disease_type", "leprosy").replace("_", " ").title() or dash
    if pdisease.lower() == "lf":
        pdisease = "LF"
    pwho = meta.get("who_grade", "").replace("_", " ").title() or dash
    pdate = meta.get("exam_date", "")
    pstate = meta.get("state", "") or dash
    pdistrict = meta.get("district", "") or dash
    pvillage = meta.get("village", "") or dash
    pcenter = meta.get("capture_center", "") or dash
    pdoctor = meta.get("referring_doctor", "") or dash
    pcaptured = meta.get("captured_by", "") or dash
    notes = meta.get("clinical_notes", "")
    pphone = meta.get("phone", "") or dash
    pref = meta.get("reference_type", "") or dash
    if pref != dash:
        pref = pref.replace("_", " ").title()
    p_rows = f"<tr><td><b>Patient ID</b></td><td>{pid}</td><td><b>Name</b></td><td>{pname}</td></tr>"
    p_rows += f"<tr><td><b>Age</b></td><td>{page} yrs</td><td><b>Gender</b></td><td>{pgender}</td></tr>"
    p_rows += f"<tr><td><b>Phone</b></td><td>{pphone}</td><td><b>Aadhar</b></td><td>{paadhar}</td></tr>"
    p_rows += f"<tr><td><b>ABHA ID</b></td><td>{pabha}</td><td><b>WHO Grade</b></td><td>{pwho}</td></tr>"
    p_rows += f"<tr><td><b>Disease Type</b></td><td>{pdisease}</td><td></td><td></td></tr>"
    p_rows += f"<tr><td><b>Diabetes</b></td><td>{pdiab}</td><td><b>Amputated Toes</b></td><td>{pamput}</td></tr>"
    p_rows += f"<tr><td><b>State</b></td><td>{pstate}</td><td><b>District</b></td><td>{pdistrict}</td></tr>"
    p_rows += f"<tr><td><b>Village</b></td><td>{pvillage}</td><td><b>Capture Center</b></td><td>{pcenter}</td></tr>"
    p_rows += f"<tr><td><b>Exam Date</b></td><td>{pdate}</td><td><b>Referring Doctor</b></td><td>{pdoctor}</td></tr>"
    p_rows += f"<tr><td><b>Captured By</b></td><td>{pcaptured}</td><td><b>Reference Marker</b></td><td>{pref}</td></tr>"
    if notes:
        p_rows += f"<tr><td><b>Clinical Notes</b></td><td colspan='3'>{notes}</td></tr>"

    q_badge_color = "#16a34a" if quality == "trusted" else "#f59e0b" if quality == "degraded" else "#dc2626"
    estimated_note = "" if quality == "trusted" else f'<div style="background:#fffbeb;border:1px solid #f59e0b;border-radius:8px;padding:10px 14px;margin:12px 0;font-size:0.88rem;color:var(--warn-text);"><strong>Note:</strong> Quality is <b>{quality}</b>. Measurements shown are estimates and may be less accurate.</div>'
    submitted = meta.get("submitted_at", "")

    html = f"""<!doctype html>
<html><head>
<meta charset="utf-8">
<title>Report &mdash; {patient_id}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Inter', sans-serif; color: #1a1a1a; padding: 32px 40px; max-width: 1000px; margin: auto; }}
  .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 3px solid #2563eb; padding-bottom: 14px; margin-bottom: 24px; }}
  .header h1 {{ font-size: 1.6rem; font-weight: 800; color: #2563eb; }}
  .header .meta {{ text-align: right; font-size: 0.82rem; color: #666; }}
  .quality {{ display: inline-block; padding: 3px 12px; border-radius: 12px; font-size: 0.78rem; font-weight: 700; text-transform: uppercase; color: #fff; background: {q_badge_color}; }}
  h2 {{ font-size: 1rem; font-weight: 700; color: #2563eb; margin: 24px 0 10px; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; margin-bottom: 10px; }}
  th, td {{ padding: 8px 12px; border: 1px solid #e2e8f0; text-align: left; }}
  thead th {{ background: #f8fafb; font-weight: 700; text-transform: uppercase; font-size: 0.8rem; color: #64748b; }}
  .patient-table td {{ border: none; border-bottom: 1px solid #f0f2f5; padding: 6px 12px; }}
  .patient-table td b {{ color: #64748b; font-size: 0.82rem; }}
  .footer {{ margin-top: 32px; text-align: center; font-size: 0.78rem; color: #aaa; border-top: 1px solid #e2e8f0; padding-top: 12px; }}
  .no-print {{ margin-bottom: 20px; text-align: center; }}
  .no-print button {{ padding: 10px 28px; border: none; border-radius: 6px; background: #2563eb; color: #fff; font-family: inherit; font-weight: 700; font-size: 0.95rem; cursor: pointer; }}
  .no-print button:hover {{ background: #1d4ed8; }}
  @media print {{
    .no-print {{ display: none; }}
    body {{ padding: 0; }}
  }}
</style>
</head><body>
<div class="no-print"><button onclick="window.print()">Print / Save as PDF</button></div>
<div class="header">
  <h1>LEPRA &mdash; Foot Measurement Report</h1>
  <div class="meta">
    <div>Run: {run_id}</div>
    <div>{submitted}</div>
    <div style="margin-top:4px;"><span class="quality">{quality}</span></div>
  </div>
</div>

<h2>Patient Information1</h2>
<table class="patient-table">{p_rows}</table>

<h2>Measurements</h2>
{estimated_note}
<table>
  <thead><tr><th>Measurement</th><th style="text-align:right">Left</th><th style="text-align:right">Right</th></tr></thead>
  <tbody>{meas_rows}</tbody>
</table>
{cross_foot_warning}

{{tech_section}}

{{viz_section}}

{{manual_section}}

<div class="footer">Generated by LEPRA Foot Measurement System &bull; IIHMR Bangalore &bull; ADMIRE</div>
</body></html>"""

    # Build landmark visualization section
    viz_html = ""
    lm_images = sorted(output_dir.glob("*_lm.jpg")) if output_dir.exists() else []
    if lm_images:
        # Local files available — embed as base64
        viz_html += '<h2>Landmark Predictions</h2><div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px;">'
        for img_path in lm_images:
            b64 = base64.b64encode(img_path.read_bytes()).decode()
            label = img_path.stem.replace(patient_id + "_", "").replace("_lm", "").replace("_", " ").title()
            viz_html += f'<div style="text-align:center"><img src="data:image/jpeg;base64,{b64}" style="max-width:100%;border-radius:6px;border:1px solid #e2e8f0;"><div style="font-size:0.82rem;color:#666;margin-top:4px;">{label}</div></div>'
        viz_html += '</div>'
    elif fs_doc and fs_doc.get("storage_lm"):
        # Firestore URLs fallback
        viz_html += '<h2>Landmark Predictions</h2><div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px;">'
        for key, url in fs_doc["storage_lm"].items():
            label = key.replace("_lm", "").replace("_", " ").title()
            viz_html += f'<div style="text-align:center"><img src="{url}" style="max-width:100%;border-radius:6px;border:1px solid #e2e8f0;"><div style="font-size:0.82rem;color:#666;margin-top:4px;">{label}</div></div>'
        viz_html += '</div>'

    html = html.replace("{viz_section}", viz_html)

    # ── Technician (footwear preparation) section ─────────────────────────
    # Same fallback rule as the SPA: prefer AI fused value; fall back to the
    # manual entry when AI value is missing or rejected by sanity gate. The
    # final value is then transformed: foot length +20mm, ball ×0.60,
    # instep ×0.85, malleoli verbatim.
    _tech_manual = meta.get("manual_measurements", {})
    def _manual_mm(side: str, mkey: str):
        v = (_tech_manual.get(mkey, {}) or {}).get(side, "")
        if v in (None, ""):
            return None
        try:
            return float(v) * 10.0  # form values are cm; convert to mm
        except (TypeError, ValueError):
            return None
    def _ai_or_manual(side_data: dict, side: str, ai_key: str, m_key: str):
        ai = side_data.get(ai_key) or {}
        v = ai.get("value_mm")
        if v is not None and ai.get("quality") != "rejected_implausible":
            try:
                return float(v), "ai"
            except (TypeError, ValueError):
                pass
        mv = _manual_mm(side, m_key)
        if mv is not None:
            return mv, "manual"
        return None, None
    def _tech_for_side(side_data: dict, side: str):
        fl, fl_src = _ai_or_manual(side_data, side, "foot_length_mm",             "foot_length")
        bg, bg_src = _ai_or_manual(side_data, side, "ball_girth_mm_provisional",  "ball_girth")
        ig, ig_src = _ai_or_manual(side_data, side, "instep_girth_mm_provisional","instep_girth")
        mh, mh_src = _ai_or_manual(side_data, side, "malleoli_height_mm",         "malleoli_height")
        return [
            ("Foot Length (+2 cm)", (fl + 20.0) if fl is not None else None, fl_src),
            ("Ball Girth (60%)",    (bg * 0.60) if bg is not None else None, bg_src),
            ("Instep Girth (85%)",  (ig * 0.85) if ig is not None else None, ig_src),
            ("Height of Malleoli",   mh,                                      mh_src),
        ]
    tech_left  = _tech_for_side(left_data,  "left")
    tech_right = _tech_for_side(right_data, "right")
    def _tech_cell(value, src):
        if value is None:
            return "—"
        cm = f"{value/10:.1f} cm"
        if src == "manual":
            return f"{cm} <span style='font-size:0.72rem;color:var(--warn-text);background:#fef3c7;padding:1px 5px;border-radius:3px;margin-left:4px;'>from manual</span>"
        return cm
    tech_rows = ""
    for i, (label, lv, ls) in enumerate(tech_left):
        _, rv, rs = tech_right[i]
        tech_rows += (
            f"<tr><td>{label}</td>"
            f"<td style='text-align:right'>{_tech_cell(lv, ls)}</td>"
            f"<td style='text-align:right'>{_tech_cell(rv, rs)}</td></tr>"
        )
    has_any_tech = any(lv is not None for _, lv, _ in tech_left) or any(rv is not None for _, rv, _ in tech_right)
    if has_any_tech:
        tech_section = (
            "<h2>Footwear Preparation Values</h2>"
            "<table>"
            "<thead><tr><th>Measurement</th><th style='text-align:right'>Left</th><th style='text-align:right'>Right</th></tr></thead>"
            f"<tbody>{tech_rows}</tbody>"
            "</table>"
            "<div style='font-size:0.78rem;color:#6b7280;margin-top:6px;'>"
            "Adjustments applied: foot length +2 cm, ball girth &times;60%, instep girth &times;85%. "
            "Used by technicians for last preparation."
            "</div>"
        )
    else:
        tech_section = ""
    html = html.replace("{tech_section}", tech_section)

    # Build manual measurements section
    manual_meas = meta.get("manual_measurements", {})
    manual_labels = [
        ("foot_length",     "Foot Length",     "cm"),
        ("ball_girth",      "Ball Girth",      "cm"),
        ("instep_girth",    "Instep Girth",    "cm"),
        ("malleoli_height", "Malleoli Height", "cm"),
    ]
    manual_rows = ""
    for key, label, unit in manual_labels:
        vals = manual_meas.get(key, {})
        l_val = vals.get("left", "")
        r_val = vals.get("right", "")
        l_str = f"{float(l_val):.2f} {unit}" if l_val else "\u2014"
        r_str = f"{float(r_val):.2f} {unit}" if r_val else "\u2014"
        manual_rows += f"<tr><td>{label}</td><td style='text-align:right'>{l_str}</td><td style='text-align:right'>{r_str}</td></tr>"
    if manual_rows:
        manual_section = f"<h2>Manual Measurements (Tape)</h2><table><thead><tr><th>Measurement</th><th style='text-align:right'>Left</th><th style='text-align:right'>Right</th></tr></thead><tbody>{manual_rows}</tbody></table>"
    else:
        manual_section = ""
    html = html.replace("{manual_section}", manual_section)

    return HTMLResponse(html)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
