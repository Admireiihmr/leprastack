import { useEffect, useRef, useState } from 'react';
import { uploadImage } from '../../../lib/api';
import { useTranslation } from '../../../i18n/I18nContext';
import GeoCaptureButton from '../../../components/GeoCaptureButton';

// Today's date as YYYY-MM-DD in the device's local timezone (for the date input).
const todayLocal = () => {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
};

// The canonical 11-symptom leprosy screening checklist (PDF order). The agent
// answers Yes/No for each; the data is sent to the Medical Officer for review.
const SYMPTOMS = [
  { key: 'skin_patches', label: 'Light-coloured or reddish skin patch(es)' },
  { key: 'patch_loss_of_sensation', label: 'Reduced or loss of sensation over skin patch(es)' },
  { key: 'numb_tingling_burning', label: 'Tingling, numbness, or burning sensation in hands/feet' },
  { key: 'weakness_in_hands_or_feet', label: 'Weakness in hands or feet' },
  { key: 'weak_grip', label: 'Weak grip or objects slipping from hands' },
  { key: 'painless_wounds', label: 'Painless wounds, burns, or ulcers on hands/feet' },
  { key: 'nerve_tenderness', label: 'Pain or tenderness near elbow, wrist, knee, or ankle' },
  { key: 'foot_drop', label: 'Foot slipping out of slippers/chappals or dragging while walking' },
  { key: 'eye_closure_difficulty', label: 'Difficulty closing eyes completely or reduced blinking' },
  { key: 'eyebrow_loss_nasal_collapse', label: 'Loss of eyebrows, collapsed nose' },
  { key: 'nodules_or_earlobe_swelling', label: 'Lumps/nodules on skin or swelling of earlobes' },
];

function YesNo({ value, onChange }) {
  const { t } = useTranslation();
  return (
    <div className="inline-flex rounded-md border border-[color:var(--border)] overflow-hidden">
      {[{ v: true, label: t('common.yes') }, { v: false, label: t('common.no') }].map(({ v, label }, idx) => {
        const selected = value === v;
        return (
          <button
            key={String(v)} type="button" onClick={() => onChange(v)}
            className={(selected ? 'bg-brand-600 text-white' : 'bg-[color:var(--surface)] t-soft hover:bg-[color:var(--surface-2)]')
              + ' px-4 py-1.5 text-sm font-medium' + (idx === 0 ? ' border-r border-[color:var(--border)]' : '')}
          >{label}</button>
        );
      })}
    </div>
  );
}

export default function ScreenStep({ onDone, initial, busy: parentBusy }) {
  const { t } = useTranslation();
  const fileInputRef = useRef(null);
  const [s, setS] = useState(() => {
    const init = initial || {};
    return {
      symptoms: {},
      duration_months: init.duration_months ?? '',
      family_history_leprosy: typeof init.family_history_leprosy === 'boolean' ? init.family_history_leprosy : null,
      image_urls: [], image_blobs: [], lab_urls: [], lab_blobs: [],
      notes: '', geolocation: null,
      ...init,
      // Default the screening date to today (the day the patient is screened).
      screened_at: init.screened_at || todayLocal(),
    };
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submitBusy = busy || parentBusy;

  const set = (k, v) => setS((cur) => ({ ...cur, [k]: v }));

  // Auto-capture the device location once on entry (the agent screens the
  // patient on-site), unless it was already captured for this draft.
  useEffect(() => {
    if (s.geolocation || typeof navigator === 'undefined' || !navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => set('geolocation', {
        lat: pos.coords.latitude,
        lng: pos.coords.longitude,
        accuracy: pos.coords.accuracy,
        altitude: pos.coords.altitude,
        captured_at: new Date(pos.timestamp).toISOString(),
      }),
      () => { /* user denied / unavailable — they can capture manually */ },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const setSymptom = (key, v) =>
    setS((cur) => ({ ...cur, symptoms: { ...cur.symptoms, [key]: v } }));

  const answered = SYMPTOMS.filter((q) => typeof s.symptoms[q.key] === 'boolean').length;
  const yesCount = SYMPTOMS.filter((q) => s.symptoms[q.key] === true).length;

  const uploadInto = (field, blobField, fallbackName) => async (e) => {
    const files = Array.from(e.target.files || []);
    for (const f of files) {
      try {
        const { url } = await uploadImage(f);
        setS((cur) => ({ ...cur, [field]: [...cur[field], url] }));
      } catch (err) {
        if (err.offline) {
          const localUrl = URL.createObjectURL(f);
          const id = crypto.randomUUID();
          setS((cur) => ({ ...cur, [blobField]: [...cur[blobField], { id, blob: f, filename: f.name || fallbackName, localUrl }] }));
        } else { throw err; }
      }
    }
  };
  const handleUpload = uploadInto('image_urls', 'image_blobs', 'image.jpg');
  const handleLabUpload = uploadInto('lab_urls', 'lab_blobs', 'lab.jpg');
  const removeAt = (field, idx) => setS((cur) => ({ ...cur, [field]: cur[field].filter((_, i) => i !== idx) }));
  const removeBlob = (field, id) => setS((cur) => ({ ...cur, [field]: cur[field].filter((b) => b.id !== id) }));

  const submit = (e) => {
    e.preventDefault();
    setError(null);
    if (answered < SYMPTOMS.length) {
      setError('Please answer all symptom questions (Yes/No) before continuing.');
      return;
    }
    if (s.duration_months === '' || Number(s.duration_months) < 0) {
      setError('Please enter the duration of symptoms in months.');
      return;
    }
    if (typeof s.family_history_leprosy !== 'boolean') {
      setError('Please select whether there is household contact with leprosy.');
      return;
    }
    setBusy(true);
    try {
      const payload = {
        symptoms: s.symptoms,
        symptoms_checklist: SYMPTOMS.filter((q) => s.symptoms[q.key] === true).map((q) => q.key),
        duration_months: Number(s.duration_months),
        family_history_leprosy: s.family_history_leprosy,
        screened_at: s.screened_at ? new Date(s.screened_at).toISOString() : new Date().toISOString(),
        geolocation: s.geolocation,
        image_urls: s.image_urls, image_blobs: s.image_blobs,
        lab_urls: s.lab_urls, lab_blobs: s.lab_blobs,
        notes: s.notes,
      };
      onDone(payload, s);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="card-elev">
      <header className="mb-5">
        <h2 className="text-lg font-semibold t-ink">Step 2 · Symptoms</h2>
        <p className="text-sm t-muted mt-1">Complete the screening questions, then continue to other investigations.</p>
      </header>

      {/* Screening context */}
      <section>
        <div className="section-title mb-3">Screening Context</div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium t-soft mb-1.5">Date of screening</label>
            <input type="date" className="neu-input" value={s.screened_at} onChange={(e) => set('screened_at', e.target.value)} />
          </div>
          <div>
            <label className="block text-xs font-medium t-soft mb-1.5">Location (GPS)</label>
            <GeoCaptureButton value={s.geolocation} onCapture={(g) => set('geolocation', g)} />
          </div>
        </div>
      </section>

      {/* 11-symptom checklist */}
      <section className="border-t border-[color:var(--border)] pt-5 mt-5">
        <div className="flex items-center justify-between mb-3">
          <div className="section-title !mb-0">Symptom Screening</div>
          <span className="text-xs t-muted">{answered}/{SYMPTOMS.length} answered · {yesCount} yes</span>
        </div>
        <div className="divide-y divide-[color:var(--border)] border border-[color:var(--border)] rounded-md overflow-hidden">
          {SYMPTOMS.map((q, i) => {
            const val = s.symptoms[q.key];
            const unanswered = error && typeof val !== 'boolean';
            return (
              <div
                key={q.key}
                className={`flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-5 px-4 py-3.5 ${unanswered ? 'bg-red-50' : ''}`}
              >
                <div className="flex-1 min-w-0 flex items-start gap-3">
                  <span className="w-6 h-6 shrink-0 grid place-items-center rounded-md text-xs font-bold bg-brand-50 text-brand-700">
                    {i + 1}
                  </span>
                  <span className="text-sm font-medium t-ink">{q.label}</span>
                </div>
                <div className="shrink-0 sm:ml-auto pl-9 sm:pl-0">
                  <YesNo value={val} onChange={(v) => setSymptom(q.key, v)} />
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="border-t border-[color:var(--border)] pt-5 mt-5">
        <div className="section-title mb-3">Symptom Details</div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium t-soft mb-1.5">
              Duration of symptoms (in months)
              <span className="text-red-600 ml-0.5" aria-hidden>*</span>
            </label>
            <input
              type="number"
              min={0}
              className="neu-input"
              required
              value={s.duration_months}
              onChange={(e) => set('duration_months', e.target.value)}
              placeholder="Enter number of months"
            />
          </div>
          <div>
            <label className="block text-xs font-medium t-soft mb-1.5">
              Household contact with leprosy
              <span className="text-red-600 ml-0.5" aria-hidden>*</span>
            </label>
            <YesNo value={s.family_history_leprosy} onChange={(v) => set('family_history_leprosy', v)} />
          </div>
        </div>
      </section>

      {/* Images */}
      <section className="border-t border-[color:var(--border)] pt-5 mt-5">
        <div className="section-title mb-3">{t('screen.images')}</div>
        <div onClick={() => fileInputRef.current?.click()}
          className="border border-dashed border-[color:var(--border-strong)] rounded-md p-6 text-center cursor-pointer hover:bg-[color:var(--surface-2)]">
          <div className="w-10 h-10 rounded-md bg-brand-50 grid place-items-center mx-auto mb-2 text-brand-700"><UploadIcon /></div>
          <div className="text-sm font-medium t-ink">Click to upload or take photo</div>
          <div className="text-xs t-muted mt-0.5">PNG, JPG · up to 10MB each</div>
          <input ref={fileInputRef} type="file" multiple accept="image/*" capture="environment" onChange={handleUpload} className="hidden" />
        </div>
        <Thumbs urls={s.image_urls} blobs={s.image_blobs} onRemoveUrl={(i) => removeAt('image_urls', i)} onRemoveBlob={(id) => removeBlob('image_blobs', id)} />
      </section>

      {/* Lab investigations */}
      <section className="border-t border-[color:var(--border)] pt-5 mt-5">
        <div className="section-title mb-3">Lab investigations</div>
        <p className="text-xs t-muted mb-3">Upload prior lab reports (skin smear, biopsy, blood work) if available.</p>
        <input type="file" multiple accept="image/*" onChange={handleLabUpload} className="text-sm t-soft" />
        <Thumbs urls={s.lab_urls} blobs={s.lab_blobs} onRemoveUrl={(i) => removeAt('lab_urls', i)} onRemoveBlob={(id) => removeBlob('lab_blobs', id)} />
      </section>

      {/* Notes */}
      <section className="border-t border-[color:var(--border)] pt-5 mt-5">
        <div className="section-title mb-3">{t('screen.notes')}</div>
        <textarea className="neu-input" rows={3} value={s.notes} onChange={(e) => set('notes', e.target.value)} placeholder={t('screen.notes_ph')} />
      </section>

      {error && <div className="text-sm text-red-700 border border-red-200 bg-red-50 rounded-md px-3 py-2 mt-4">{error}</div>}

      <div className="flex justify-end mt-6">
        <button className="btn-primary inline-flex items-center gap-1.5" disabled={submitBusy}>
          {submitBusy ? '…' : (
            <>
              Continue to Other Investigations
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 12h14" /><path d="M12 5l7 7-7 7" />
              </svg>
            </>
          )}
        </button>
      </div>
    </form>
  );
}

function Thumbs({ urls, blobs, onRemoveUrl, onRemoveBlob }) {
  if (urls.length === 0 && blobs.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-3 mt-3">
      {urls.map((u, i) => (
        <div key={`url-${i}`} className="relative group">
          <img src={u} alt="" className="w-24 h-24 object-cover rounded-md border border-[color:var(--border)]" />
          <RemoveBtn onClick={() => onRemoveUrl(i)} />
        </div>
      ))}
      {blobs.map((item) => (
        <div key={item.id} className="relative group">
          <img src={item.localUrl} alt="" className="w-24 h-24 object-cover rounded-md border border-amber-300" />
          <span className="absolute bottom-0 left-0 right-0 text-[9px] font-semibold text-center bg-amber-100/90 text-amber-800 py-0.5 rounded-b-md">Pending upload</span>
          <RemoveBtn onClick={() => onRemoveBlob(item.id)} />
        </div>
      ))}
    </div>
  );
}

function RemoveBtn({ onClick }) {
  return (
    <button type="button" onClick={onClick} aria-label="Remove"
      className="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-red-600 text-white grid place-items-center text-xs opacity-0 group-hover:opacity-100">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6L6 18M6 6l12 12" /></svg>
    </button>
  );
}

function UploadIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" />
    </svg>
  );
}
