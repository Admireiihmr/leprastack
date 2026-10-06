import { useState } from 'react';
import { uploadImage } from '../../../lib/api';
import { useTranslation } from '../../../i18n/I18nContext';

const CHRONIC = ['Diabetes', 'Hypertension', 'TB', 'HIV', 'Pregnancy', 'None'];

export default function HistoryStep({ patient, onDone, initial, busy: parentBusy }) {
  const { t } = useTranslation();
  // Pregnancy is not applicable to male patients.
  const isMale = patient?.sex === 'male';
  const conditions = CHRONIC.filter((c) => !(isMale && c === 'Pregnancy'));
  const [chronic, setChronic] = useState(initial?.chronic_conditions || []);
  const [notes, setNotes] = useState(initial?.past_visits_notes || '');
  const [rxUrls, setRxUrls] = useState(initial?.prior_prescriptions_urls || []);
  const [labUrls, setLabUrls] = useState(initial?.prior_labs_urls || []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submitBusy = busy || parentBusy;

  const toggleChronic = (c) =>
    setChronic((arr) => (arr.includes(c) ? arr.filter((x) => x !== c) : [...arr, c]));

  const handleUpload = async (e) => {
    const files = Array.from(e.target.files || []);
    for (const f of files) {
      const { url } = await uploadImage(f);
      setRxUrls((u) => [...u, url]);
    }
  };

  const handleLabUpload = async (e) => {
    const files = Array.from(e.target.files || []);
    for (const f of files) {
      const { url } = await uploadImage(f);
      setLabUrls((u) => [...u, url]);
    }
  };

  const submit = (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const draft = {
        chronic_conditions: isMale ? chronic.filter((c) => c !== 'Pregnancy') : chronic,
        prior_prescriptions_urls: rxUrls,
        prior_labs_urls: labUrls,
        past_visits_notes: notes,
      };
      onDone(draft, draft);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="card-elev">
      <header className="mb-5">
        <h2 className="text-lg font-semibold t-ink">Step 3 · Other Investigations</h2>
        <p className="text-sm t-muted mt-1">
          {patient?.name} · {patient?.age}y · {patient?.sex}
        </p>
      </header>

      <section>
        <div className="section-title mb-3">{t('history.chronic')}</div>
        <div className="flex flex-wrap gap-2">
          {conditions.map((c) => {
            const selected = chronic.includes(c);
            return (
              <button
                type="button"
                key={c}
                onClick={() => toggleChronic(c)}
                className={
                  selected
                    ? 'px-3 py-1.5 rounded-md text-sm font-medium border bg-brand-50 text-brand-700 border-brand-200'
                    : 'px-3 py-1.5 rounded-md text-sm font-medium border bg-[color:var(--surface)] t-soft border-[color:var(--border)] hover:border-[color:var(--border-strong)]'
                }
              >
                {t('chronic.' + c, c)}
              </button>
            );
          })}
        </div>
      </section>

      <section className="border-t border-[color:var(--border)] pt-5 mt-5">
        <div className="section-title mb-3">{t('history.priorRx')}</div>
        <input type="file" multiple accept="image/*" onChange={handleUpload} className="text-sm t-soft" />
        {rxUrls.length > 0 && (
          <p className="text-xs t-muted mt-1.5">
            {t('history.files').replace('{n}', rxUrls.length)}
          </p>
        )}
      </section>

      <section className="border-t border-[color:var(--border)] pt-5 mt-5">
        <div className="section-title mb-3">Prior lab reports</div>
        <input type="file" multiple accept="image/*" onChange={handleLabUpload} className="text-sm t-soft" />
        {labUrls.length > 0 && (
          <p className="text-xs t-muted mt-1.5">{labUrls.length} file{labUrls.length === 1 ? '' : 's'} uploaded</p>
        )}
      </section>

      <section className="border-t border-[color:var(--border)] pt-5 mt-5">
        <div className="section-title mb-3">{t('history.notes')}</div>
        <textarea
          className="neu-input"
          rows={3}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder={t('history.notes_ph')}
        />
      </section>

      {error && (
        <div className="text-sm text-red-700 border border-red-200 bg-red-50 rounded-md px-3 py-2 mt-4">
          {error}
        </div>
      )}

      <div className="flex justify-end mt-6">
        <button className="btn-primary" disabled={submitBusy}>
          {submitBusy ? '…' : 'Submit to Medical Officer'}
        </button>
      </div>
    </form>
  );
}
