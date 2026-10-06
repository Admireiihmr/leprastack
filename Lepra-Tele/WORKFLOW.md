# Tele-Leprosy Triage Console — Workflow Document

A field-to-specialist tele-leprosy screening and triage platform for the SHAKTHI
programme (Bastar district, Chhattisgarh). Field agents screen patients on-site,
data is sent to a Medical Officer (MO) for tele-consultation and decision, and
administrators oversee the operation.

---

## 1. Roles

| Role                           | Who                                | What they do                                                                                                                                        |
| ------------------------------ | ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Field Agent**          | Community health worker / mediator | Enrol patients, capture history + the 11-symptom leprosy screening on-site, submit to the MO. No clinical decision.                                 |
| **Medical Officer (MO)** | Doctor                             | Review the agent's submission, run a Zoom tele-consult, record a clinical assessment, and issue a decision (close / alternative diagnosis / refer). |
| **Administrator**        | Programme admin                    | Monitor the dashboard (metrics, escalations), manage users, and review the audit log. Provisioned out-of-band (no self-registration).               |

> Patients do **not** log in. They are enrolled by an agent and receive updates via WhatsApp.

---

## 2. High-level flow

```
        ┌──────────────┐        ┌──────────────────┐        ┌────────────────┐
        │  FIELD AGENT │        │  MEDICAL OFFICER │        │  ADMINISTRATOR │
        └──────┬───────┘        └────────┬─────────┘        └───────┬────────┘
               │ 1. Enrol + screen        │                          │
               │ 2. Submit to MO          │                          │
               ▼                          │                          │
        ┌──────────────┐                  │                          │
        │  Case created│ ── awaiting_mo ─▶│ 3. Review + schedule     │
        │  (Firestore) │                  │ 4. Zoom tele-consult     │
        └──────────────┘                  │ 5. Clinical assessment   │
               ▲                          │ 6. Decision              │
               │   WhatsApp updates       ▼                          │
        ┌──────┴───────┐        ┌──────────────────┐                 │
        │   PATIENT    │◀───────│ close / refer / │                 │
        │  (WhatsApp)  │        │ alternative dx   │                 │
        └──────────────┘        └──────────────────┘                 │
                                        │                            │
                                        └──── metrics / audit ──────▶│
```

---

## 3. Authentication & onboarding

- **Login page** has three role cards: **Field Agent**, **Medical Officer**, **Administrator**.
  - A card only logs in its own role — signing in with another role's credentials is rejected and signed out.
  - **Agent & MO** can self-register (Sign in / Register toggle). Registration captures **name, phone (10 digits), email, password**. Phone can be changed later in **Settings → Profile**.
  - **Administrator** is **login-only** (provisioned by an admin; no public sign-up).
- Auth is **Firebase Authentication**; the role lives on the user's Firestore profile and is mirrored to a custom token claim.
- Phone numbers are used to send WhatsApp notifications to agents and MOs.

---

## 4. Field Agent workflow (3-step intake wizard)

The agent intake is a single wizard that batches all writes for **offline safety**
(works with no connectivity; syncs when back online).

### Step 1 — Enrollment

- **Programme context:** select **PHC / CHC** (Bakawand, Karpawand, Kolawal, Mangnaar, Kachnaar, Maalgaon, Jebel). Selecting a PHC **auto-fills State (Chhattisgarh) and District (Bastar)**.
- **Patient identity:** name, age, sex, **phone (exactly 10 digits)**.
- **Contact & location:** state/district (auto), village, gram panchayat, house no.
- **Household:** household number, relation to head, head-of-family name + phone.
- **Health identifiers:** Aadhaar (12 digits), ABHA (14 digits) — optional.
- Consent checkbox (required).

### Step 2 — History

- **Chronic conditions:** Diabetes, Hypertension, TB, HIV, Pregnancy, None.
  - **"Pregnancy" is hidden for male patients.**
- Optional prior prescription / lab photos and past-visit notes.

### Step 3 — Symptoms

- **Screening context:** Date of screening **auto-set to today**; **GPS location auto-captured** on entry (re-capturable).
- **11-question leprosy symptom checklist** (numbered, Yes/No each):
  1. Light-coloured or reddish skin patch(es)
  2. Reduced or loss of sensation over skin patch(es)
  3. Tingling, numbness, or burning sensation in hands/feet
  4. Weakness in hands or feet
  5. Weak grip or objects slipping from hands
  6. Painless wounds, burns, or ulcers on hands/feet
  7. Pain or tenderness near elbow, wrist, knee, or ankle
  8. Foot slipping out of slippers/chappals or dragging while walking
  9. Difficulty closing eyes completely or reduced blinking
  10. Loss of eyebrows, collapsed nose
  11. Lumps/nodules on skin or swelling of earlobes
- **Lesion photos** and **lab report** uploads.
- **Submit to Medical Officer** — the agent makes **no decision**; every case is routed to the MO queue.

### What happens on submit

1. The full intake (patient + history + screening + images) is queued in IndexedDB and uploaded (immediately if online, on reconnect if offline).
2. Backend creates the **patient** + **case**, stores the screening, and computes a **leprosy risk summary** (High / Moderate / Low) for the MO's reference only.
3. Case status → **awaiting_mo**.
4. Artefacts are gathered into the patient's Storage folder (agent report PDF, images, labs — see §8).

---

## 5. Medical Officer workflow

### Queue

- The MO sees their cases (patient name, case ID, status). Risk labels are intentionally **not** shown here.

### Case Review (collapsible cards to reduce scrolling)

1. **Tele-consult** — schedule a Zoom slot (date/time + duration). Booking:
   - Creates a Zoom meeting and sends the **join link via WhatsApp to the patient, the agent, and the MO**.
   - Case status → **scheduled**.
   - **"Start Zoom consult"** is enabled around the slot time (host link opens Zoom).
   - **Screen recording:** the MO can record the consultation (browser screen capture); the recording uploads to the patient folder.
2. **Intake by field agent** (collapsible) — full read-only view of demographics, history, the 11 symptom answers, lesion images, and lab reports.
3. **MO clinical assessment** (collapsible, numbered 1–9): confirmed leprosy, no. of skin lesions, nerve involvement grid, status of case, WHO classification, sensory loss, disability grade, complications, treatment plan. **Must be saved before a decision.**
4. **Post-consultation** — upload reports/prescriptions (PDF/image) and view recordings; all stored in the patient folder.
5. **Decision** — one of:
   - **Close at community level** (`close_remote`)
   - **Alternative diagnosis** (`alt_dx`)
   - **Refer** (`refer`)

### On decision ("Save decision & notify")

- The decision is **saved first** (independent of WhatsApp), the **MO report PDF** is generated and stored in the patient folder.
- A WhatsApp message (with the MO report attached) is sent to the **patient and the agent** — **not** the MO.
- Case status → `closed_remote` / `closed_alt_dx` / `referred`.

### Expired sessions = read-only

- If a consult slot has **passed**, the case becomes **read-only**: a banner is shown, the clinical assessment fields are disabled, and the decision cannot be changed. Everything remains viewable/downloadable.

---

## 6. Administrator workflow

- **Dashboard** — operational metrics (case counts by outcome, recent escalations, pending image cases). "View all patients" opens the patient directory.
- **Users** — list/manage staff accounts and roles (agent / mo / admin).
- **Audit** — system audit log.

---

## 7. Notifications (WhatsApp)

| Event                               | Recipients                         | Content                             |
| ----------------------------------- | ---------------------------------- | ----------------------------------- |
| Tele-consult scheduled              | **Patient + Agent + MO**     | Zoom join link, time, duration      |
| MO decision issued                  | **Patient + Agent** (not MO) | Outcome + next step + MO report PDF |
| Community close / rule-out (legacy) | Patient                            | Outcome + advice                    |

Requires approved Meta WhatsApp templates: `appointment_scheduled`, `triage_decision`, `triage_decision_with_report`. Recipients without a saved phone are skipped gracefully.

---

## 8. Document storage (per-patient folder)

All artefacts for a patient are organised under one Storage folder:

```
patients/<case-id>__<patient-name-slug>/
├── agent-report-<id>.pdf       # generated on screening submit
├── mo-report-<id>.pdf          # generated on MO decision
├── images/image-1.jpg …        # lesion photos from intake
├── labs/lab-1.jpg …            # lab reports from intake
├── consultation/<ts>-<file>    # MO post-consult uploads
└── recordings/consultation-<ts>.webm   # screen recordings
```

- **Agent Report** = the intake PDF (everything the agent captured).
- **MO Report** = the decision PDF (clinical assessment + final decision).

---

## 9. Case status lifecycle

```
intake ─▶ awaiting_mo ─▶ scheduled ─▶ (consult) ─▶ closed_remote
                                                  ├▶ closed_alt_dx
                                                  └▶ referred
```

(`closed_rule_out` is also used for rule-out closes.)

---

## 10. Architecture & tech stack

| Layer        | Technology                                                                                             |
| ------------ | ------------------------------------------------------------------------------------------------------ |
| Frontend     | React + Vite + Tailwind CSS, PWA (installable, offline-first via IndexedDB + service worker)           |
| Backend      | FastAPI (Python)                                                                                       |
| Auth         | Firebase Authentication (email/password) + role custom claims                                          |
| Database     | Cloud Firestore (`users`, `patients`, `cases`, `appointments`, `notifications`, `recalls`) |
| File storage | Firebase Storage (per-patient folders)                                                                 |
| Video        | Zoom (meeting creation + Meeting SDK signature; host/participant links)                                |
| Messaging    | WhatsApp Business (Meta) templates                                                                     |
| PDF          | ReportLab (agent report + MO report)                                                                   |

### Offline-first

The agent intake is fully usable offline: the bundle (patient + history + screening + image blobs) is stored in IndexedDB and uploaded by the sync engine when connectivity returns. Forced submission always routes to the MO.

---

## 11. Operational prerequisites (deployment checklist)

1. **Firebase project** with Authentication, Firestore, and **Storage enabled** (the default bucket must exist — required for report/recording uploads).
2. **WhatsApp Business templates** created and approved in Meta: `appointment_scheduled`, `triage_decision`, `triage_decision_with_report`.
3. **Zoom** API credentials (for meeting creation) and Meeting SDK key/secret.
4. Service-account credentials configured for the backend (`FIREBASE_CREDENTIALS_*`, `FIREBASE_STORAGE_BUCKET`).
5. At least one **admin** provisioned out-of-band; agents and MOs self-register and add their phone.

---

## 12. End-to-end summary (one patient)

1. Agent opens the app (online or offline), enrols the patient, records history and the 11-symptom screening with photos, and **submits to the MO**.
2. The case appears in the MO queue (`awaiting_mo`); the agent report PDF + images are stored in the patient folder.
3. The MO **schedules a Zoom consult** → patient, agent, and MO get the link by WhatsApp.
4. The MO runs the consult (optionally **recording the screen**), fills the **clinical assessment**, and issues a **decision**.
5. The **MO report PDF** is generated and the decision is sent by WhatsApp to the **patient and agent**; the case is closed/referred.
6. After the slot expires, the case is **read-only**.
7. Admins monitor the whole operation via the **dashboard** and **audit log**.
