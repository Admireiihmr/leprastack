import { useState } from 'react';
import EnrollStep from './steps/EnrollStep';
import HistoryStep from './steps/HistoryStep';
import ScreenStep from './steps/ScreenStep';
import { useTranslation } from '../../i18n/I18nContext';
import { useAuth } from '../../context/AuthContext';
import { getIntakeBundle, saveIntakeBundle } from '../../lib/offlineDB';
import { drainQueue } from '../../lib/syncEngine';

export default function Intake() {
  const { t } = useTranslation();
  const { profile } = useAuth();
  const STEPS = [
    { key: 'enroll', short: 'Enrollment', desc: 'Patient identity and location' },
    { key: 'screen', short: 'Symptoms', desc: 'Screening questions' },
    { key: 'history', short: 'Other Investigations', desc: 'Medical history and uploads' },
  ];

  const [step, setStep] = useState('enroll');
  // `patient` holds the EnrollStep form payload (NOT a server-created patient
  // anymore — the wizard batches all writes for offline safety).
  const [patient, setPatient] = useState(null);
  const [screening, setScreening] = useState(null);
  const [, setHistory] = useState(null);
  const [advancing, setAdvancing] = useState(false);
  const [advanceError, setAdvanceError] = useState(null);
  // Cached form drafts so going back preserves what was typed
  const [draftEnroll, setDraftEnroll] = useState(null);
  const [draftHistory, setDraftHistory] = useState(null);
  const [draftScreen, setDraftScreen] = useState(null);

  const currentIdx = STEPS.findIndex((s) => s.key === step);
  const displayName = profile?.profile?.name || profile?.email || 'Agent';

  const reset = () => {
    setStep('enroll');
    setPatient(null);
    setScreening(null);
    setHistory(null);
    setDraftEnroll(null);
    setDraftHistory(null);
    setDraftScreen(null);
    setAdvanceError(null);
  };

  const canVisit = (key) => {
    const idx = STEPS.findIndex((s) => s.key === key);
    if (idx <= currentIdx) return true;
    if (key === 'screen') return Boolean(patient);
    if (key === 'history') return Boolean(screening);
    return false;
  };

  // ----- Final submit: queue the full intake as a bundle, then trigger drain. -----
  // The agent only collects data and sends it to the Medical Officer — there is
  // no agent-side decision. If online the bundle uploads immediately and the
  // case lands in the MO queue; if offline it stays in IndexedDB and the sync
  // engine drains it when network returns.
  const onHistorySubmitted = async (historyPayload, draft) => {
    setHistory(historyPayload);
    setDraftHistory(draft || null);
    setAdvanceError(null);
    setAdvancing(true);
    try {
      if (!screening) {
        throw new Error('Screening details are missing. Please complete the symptoms step again.');
      }
      // Strip blob entries from the screen payload before persisting — they
      // go in their own fields on the bundle so sync can multipart-upload them.
      const { image_blobs = [], lab_blobs = [], ...screenJson } = screening;
      const bundle = {
        id: crypto.randomUUID(),
        status: 'pending',
        created_at: Date.now(),
        agent_uid: profile?.uid || null,
        patient,
        history: historyPayload || {
          chronic_conditions: [],
          prior_prescriptions_urls: [],
          prior_labs_urls: [],
          past_visits_notes: null,
        },
        screen: screenJson,
        images: image_blobs.map((b) => ({ blob: b.blob, filename: b.filename })),
        lab_images: lab_blobs.map((b) => ({ blob: b.blob, filename: b.filename })),
      };
      await saveIntakeBundle(bundle);
      await drainQueue();

      const updated = await getIntakeBundle(bundle.id);
      if (updated?.status === 'synced') {
        alert('Submitted to the Medical Officer for review.');
      } else {
        alert('Saved on this device — it will upload to the Medical Officer automatically when you reconnect.');
      }
      reset();
    } catch (err) {
      setAdvanceError(err.message || 'Failed to save the intake. Try again.');
    } finally {
      setAdvancing(false);
    }
  };

  const goTo = (key) => {
    if (canVisit(key)) setStep(key);
  };

  const svgProps = { width: 14, height: 14, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' };

  return (
    <div>
      {/* Page header */}
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4 mb-6">
        <div>
          <div className="section-title">{t('role.agent')}</div>
          <h1 className="text-2xl font-semibold tracking-tight t-ink">{t('intake.title')}</h1>
          <p className="text-sm t-muted mt-1">
            {STEPS[currentIdx]?.short} · {STEPS[currentIdx]?.desc}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs t-muted">{displayName}</span>
          <span className="pill-ink">
            {currentIdx + 1} / {STEPS.length}
          </span>
        </div>
      </div>

      {/* Step chips */}
      <div className="flex flex-wrap items-center gap-2 mb-5">
        {STEPS.map((s, i) => {
          const active = i === currentIdx;
          const done = i < currentIdx;
          const clickable = canVisit(s.key);
          const cls = active ? 'step-chip-active' : done ? 'step-chip-done' : 'step-chip-todo';
          return (
            <button
              key={s.key}
              type="button"
              onClick={() => goTo(s.key)}
              disabled={!clickable}
              className={`${cls} ${!clickable ? 'opacity-60 cursor-not-allowed' : ''}`}
              title={clickable ? `Go to ${s.short}` : `${s.short} (locked)`}
            >
              <span className="text-[10px] font-semibold opacity-80">{i + 1}</span>
              <span>{s.short}</span>
            </button>
          );
        })}
      </div>

      {/* Back link */}
      {currentIdx > 0 && (
        <div className="mb-4">
          <button
            type="button"
            onClick={() => goTo(STEPS[currentIdx - 1].key)}
            className="btn-ghost inline-flex items-center gap-1.5 text-xs"
          >
            <svg {...svgProps}><path d="M19 12H5" /><path d="M12 19l-7-7 7-7" /></svg>
            Back to {STEPS[currentIdx - 1].short}
          </button>
        </div>
      )}

      {/* Step body */}
      <div>
        {step === 'enroll' && (
          <EnrollStep
            initial={draftEnroll}
            onDone={(p, draft) => { setPatient(p); setDraftEnroll(draft || null); setStep('screen'); }}
          />
        )}
        {step === 'screen' && (
          <ScreenStep
            initial={draftScreen}
            onDone={(screenPayload, draft) => {
              setScreening(screenPayload);
              setDraftScreen(draft || null);
              setStep('history');
            }}
          />
        )}
        {step === 'history' && (
          <HistoryStep
            patient={patient}
            initial={draftHistory}
            busy={advancing}
            onDone={onHistorySubmitted}
          />
        )}
        {advanceError && step === 'history' && (
          <div className="mt-3 text-sm text-red-700 border border-red-200 bg-red-50 rounded-md px-3 py-2">
            {advanceError}
          </div>
        )}
      </div>
    </div>
  );
}
