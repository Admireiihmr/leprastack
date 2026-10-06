# Tele-Leprosy Triage Web App

A tele-consultation + triage MVP for leprosy screening, built per the
spec PDF in this repo. The pipeline is the safety-net version:

```
Enroll -> History -> Pick condition -> Screen -> Rule Engine
       -> MO Review (only if escalated) -> Action -> Recall/Audit
```

**Stack**

| Layer        | Choice                                     |
|--------------|--------------------------------------------|
| Frontend     | React 18 + Vite + React Router + Tailwind  |
| Backend      | FastAPI + Pydantic v2                      |
| Database     | Firestore (via firebase-admin)             |
| File storage | Firebase Storage                           |
| Auth         | Firebase Auth (ID tokens verified server-side) |
| Video        | Zoom Meeting SDK (web)                     |

## Roles

| Role     | What they do |
|----------|-------------|
| `patient` | Self sign-up. Sees their cases + appointments. Joins Zoom consult. |
| `agent`   | Field health worker. Enrolls patients, captures history + screening, runs the rule engine, schedules MO consult on escalation. |
| `mo`      | Medical Officer. Reviews escalated cases, joins Zoom, writes Rx or referral. |
| `admin`   | Promotes users to other roles, sees metrics, audits the rule-out sample. |

Only `patient` self-registers. Other roles must be promoted by an admin
via Admin → Users.

## Project layout

```
backend/                FastAPI service
  app/
    main.py             app entry, CORS, router wiring
    core/
      config.py         env vars
      firebase.py       Firestore + Storage + Auth Admin SDK
      security.py       ID-token verification + role guard
    models/schemas.py   pydantic models
    services/
      rule_engine.py    deterministic leprosy triage
      zoom.py           Zoom Meeting SDK signature
    routers/
      auth.py           /auth/me, /bootstrap, /set-role
      patients.py       /patients
      cases.py          /cases  (history, screen, queue, decision)
      appointments.py   /appointments  + /zoom-signature
      admin.py          /admin/users, /metrics, /audit-sample, /mos
      uploads.py        /uploads/image
frontend/               React SPA
  src/
    pages/agent         Intake wizard (5 steps)
    pages/mo            Queue, CaseReview, Appointments
    pages/patient       Appointments, Cases
    pages/admin         Metrics, Users, Audit
    components/         Layout, ProtectedRoute, ZoomConsult
    context/AuthContext Firebase Auth state + role
    lib/                firebase.js, api.js
firebase/               firestore.rules, storage.rules
```

## One-time Firebase setup

1. Create a Firebase project at https://console.firebase.google.com.
2. Enable **Authentication → Email/Password**.
3. Enable **Firestore** (production mode is fine; backend uses Admin SDK so
   rules don't block it).
4. Enable **Storage**.
5. Project Settings → Service Accounts → **Generate new private key**.
   Save the JSON as `backend/serviceAccountKey.json`.
6. Project Settings → General → Your apps → register a web app, copy the
   config values into `frontend/.env`.

## Running locally

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate           # Windows
pip install -r requirements.txt
copy .env.example .env           # fill in FIREBASE_STORAGE_BUCKET etc.
uvicorn app.main:app --reload --port 8000
```

The backend expects `backend/serviceAccountKey.json` to exist.

### Frontend

```bash
cd frontend
npm install
copy .env.example .env           # fill in VITE_FIREBASE_* values
npm run dev
```

Open http://localhost:5173. Vite proxies `/api/*` → `http://localhost:8000`.

## First-run bootstrap

1. Sign up as a patient (this is the only self-registration path).
2. In the Firebase console, manually flip your test user to `admin`:
   - Firestore → `users/{uid}` → set `role: "admin"`.
   - Then in the backend, run a one-time script or call `/auth/set-role`
     once you have admin claim. Easiest path: temporarily promote yourself
     by running this in a Python REPL inside the backend venv:
     ```python
     from app.core.firebase import init_firebase, get_auth, get_db
     init_firebase()
     uid = "your-firebase-uid"
     get_auth().set_custom_user_claims(uid, {"role": "admin"})
     get_db().collection("users").document(uid).set({"role": "admin"}, merge=True)
     ```
3. Sign out and back in (the ID token refreshes claims). You're now admin.
4. Create accounts for agent + MO via the normal sign-up flow, then in
   Admin → Users, promote them.

## Zoom setup (optional)

Without Zoom credentials the app still works — `ZoomConsult` falls back to
an external `https://zoom.us/j/<id>` link. To embed video in-app:

1. Create a **Meeting SDK** app at https://marketplace.zoom.us.
2. Copy SDK Key + Secret into `backend/.env` (`ZOOM_SDK_KEY`,
   `ZOOM_SDK_SECRET`) and SDK Key into `frontend/.env`
   (`VITE_ZOOM_SDK_KEY`).
3. Restart both servers.

Backend mints a short-lived HMAC signature so the SDK secret never reaches
the browser.

## Triage rule engine

`backend/app/services/rule_engine.py` implements the deterministic logic:

- **Escalate** if any high-specificity sign (patch + sensory loss, glove-
  stocking anesthesia, enlarged nerves) OR cardinal score ≥ 3.
- **Alternative dx** if a patch exists without sensory loss and duration
  < 4 weeks. Guesses scabies/fungal/eczema from free-text notes.
- **Rule out** if no cardinal signs at all. Auto-schedules a 4–6 week
  recall in `recalls/`.
- Borderline cases default to **escalate** (false-negative tail
  protection).

Swap in an ML model later by replacing `triage_leprosy()` and keeping the
`TriageResult` shape.

## Metrics the PDF asks for

Admin → Metrics shows:

- Total cases
- **Referral rate** (target ≤25%)
- Remote-closure rate
- Breakdown by triage outcome

Admin → Audit pulls a random 5% sample of rule-outs for independent review
— this is the safety net for the missed-case rate (target ≤2%).

## Known gaps / next steps

- WhatsApp/SMS dispatch is stubbed (writes to `notifications` collection).
  Wire to Twilio or Gupshup in `routers/cases.py::mo_decision`.
- The recall scheduler creates `recalls/` docs but no cron worker reads
  them yet. Add a Cloud Function or a `apscheduler` job that posts back
  into the queue on `due_at`.
- AI pre-screening is currently the deterministic rule engine. Slot a
  PyTorch image classifier in front of it and merge the score into
  `TriageResult.confidence`.
- Nikusth / Ni-kshay / NSCAEM hand-offs are not yet wired.
- Offline-first PWA mode for village agents (PDF §10).
