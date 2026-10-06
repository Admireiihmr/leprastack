import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from '../../../i18n/I18nContext';
import { STATES, STATES_DISTRICTS } from '../../../data/districts';
import { getPhcMeta } from '../../../lib/phcMeta';


const onlyDigits = (s) => (s || '').replace(/\D/g, '');

const PHC_LOCATION = {
  Bakawand: { state: 'Chhattisgarh', district: 'Bastar' },
  Karpawand: { state: 'Chhattisgarh', district: 'Bastar' },
  Kolawal: { state: 'Chhattisgarh', district: 'Bastar' },
  Mangnaar: { state: 'Chhattisgarh', district: 'Bastar' },
  Kachnaar: { state: 'Chhattisgarh', district: 'Bastar' },
  Maalgaon: { state: 'Chhattisgarh', district: 'Bastar' },
  Jebel: { state: 'Chhattisgarh', district: 'Bastar' },
};
const DEFAULT_PHC_LOCATION = { state: 'Chhattisgarh', district: 'Bastar' };
const locationForPhc = (phc) => (phc ? PHC_LOCATION[phc] || DEFAULT_PHC_LOCATION : null);

const RELATION_OPTIONS = [
  { value: 'self', label: 'Self' },
  { value: 'father_mother', label: 'Father / Mother' },
  { value: 'husband_wife', label: 'Husband / Wife' },
  { value: 'brother_sister', label: 'Brother / Sister' },
  { value: 'son_daughter', label: 'Son / Daughter' },
  { value: 'grand_son_grand_daughter', label: 'Grand Son / Grand Daughter' },
  { value: 'others', label: 'Others' },
];

export default function EnrollStep({ onDone, initial }) {
  const { t } = useTranslation();
  const [form, setForm] = useState(() => ({
    name: '',
    age: '',
    sex: 'male',
    phone: '',
    state: '',
    district: '',
    taluk: '',
    village: '',
    aadhaar_id: '',
    abha_id: '',
    referred_by: '',
    consent_given: true,
    phc: '',
    house_no: '',
    gram_panchayat: '',
    household_number: '',
    head_of_family_name: '',
    head_of_family_phone: '',
    relation_to_head: '',
    ...(initial || {}),
  }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [touched, setTouched] = useState({});
  const [phcMeta, setPhcMeta] = useState([]);

  useEffect(() => {
    getPhcMeta().then(setPhcMeta).catch(() => setPhcMeta([]));
  }, []);

  const districts = useMemo(
    () => (form.state ? STATES_DISTRICTS[form.state] || [] : []),
    [form.state],
  );

  const phoneDigits = onlyDigits(form.phone);
  const aadhaarDigits = onlyDigits(form.aadhaar_id);
  const abhaDigits = onlyDigits(form.abha_id);

  const phoneError =
    touched.phone && !form.phone.trim()
      ? 'Phone number is required'
      : touched.phone && phoneDigits.length !== 10
        ? 'Phone must be exactly 10 digits'
        : null;

  const hofPhoneDigits = onlyDigits(form.head_of_family_phone);
  const hofPhoneError =
    touched.head_of_family_phone && hofPhoneDigits.length > 0 && hofPhoneDigits.length !== 10
      ? 'Phone must be exactly 10 digits'
      : null;

  const aadhaarError =
    touched.aadhaar_id && aadhaarDigits.length !== 12
      ? 'Aadhaar must be exactly 12 digits'
      : null;

  const abhaError =
    touched.abha_id && abhaDigits.length > 0 && abhaDigits.length !== 14
      ? 'ABHA ID must be exactly 14 digits'
      : null;

  const submit = (e) => {
    e.preventDefault();
    setTouched({ phone: true, aadhaar_id: true, abha_id: true, head_of_family_phone: true });
    if (!form.phone.trim() || phoneDigits.length !== 10) return;
    if (hofPhoneDigits.length > 0 && hofPhoneDigits.length !== 10) return;
    if (aadhaarDigits.length !== 12) return;
    if (abhaDigits.length > 0 && abhaDigits.length !== 14) return;

    setBusy(true);
    setError(null);
    try {
      const location = [form.village, form.taluk, form.district, form.state]
        .map((s) => (s || '').trim())
        .filter(Boolean)
        .join(', ');
      const payload = {
        ...form,
        phone: form.phone.trim(),
        aadhaar_id: aadhaarDigits || null,
        abha_id: abhaDigits || null,
        location,
        phc: form.phc || null,
        house_no: form.house_no || null,
        taluk: form.taluk || null,
        gram_panchayat: form.gram_panchayat || null,
        household_number: form.household_number || null,
        head_of_family_name: form.head_of_family_name || null,
        head_of_family_phone: form.head_of_family_phone || null,
        relation_to_head: form.relation_to_head || null,
      };
      onDone(payload, form);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const f = (k, v) => setForm((s) => ({ ...s, [k]: v }));
  const onStateChange = (v) => setForm((s) => ({ ...s, state: v, district: '' }));

  const onPhcChange = (v) => {
    const loc = locationForPhc(v);
    setForm((s) => ({
      ...s,
      phc: v,
      ...(loc ? { state: loc.state, district: loc.district } : {}),
    }));
  };

  return (
    <form onSubmit={submit} className="card-elev">
      <header className="mb-5">
        <h2 className="text-lg font-semibold t-ink">{t('enroll.title')}</h2>
        <p className="text-sm t-muted mt-1">{t('enroll.subtitle')}</p>
      </header>

      <section>
        <div className="section-title mb-3">Programme Context</div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="PHC / CHC" required>
            <select
              className="neu-input"
              value={form.phc}
              onChange={(e) => onPhcChange(e.target.value)}
              required
            >
              <option value="">{phcMeta.length === 0 ? 'Loading…' : 'Select PHC'}</option>
              {phcMeta.map((p) => (
                <option key={p.name} value={p.name}>{p.name}</option>
              ))}
            </select>
          </Field>
        </div>
      </section>

      <section className="border-t border-[color:var(--border)] pt-5 mt-5">
        <div className="section-title mb-3">Patient Identity</div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label={t('enroll.fullName')} required>
            <input
              className="neu-input"
              required
              value={form.name}
              onChange={(e) => f('name', e.target.value)}
              placeholder="Enter full name"
            />
          </Field>
          <Field label={t('enroll.age')} required>
            <input
              className="neu-input"
              type="number"
              min={0}
              max={120}
              required
              value={form.age}
              onChange={(e) => f('age', e.target.value === '' ? '' : +e.target.value)}
              placeholder="Enter age"
            />
          </Field>
          <Field label={t('enroll.sex')} required>
            <select className="neu-input" value={form.sex} onChange={(e) => f('sex', e.target.value)}>
              <option value="male">{t('enroll.sex.male')}</option>
              <option value="female">{t('enroll.sex.female')}</option>
              <option value="other">{t('enroll.sex.other')}</option>
            </select>
          </Field>
          <Field label={t('enroll.phone')} required error={phoneError}>
            <input
              className="neu-input"
              required
              inputMode="numeric"
              maxLength={10}
              value={form.phone}
              onChange={(e) => f('phone', onlyDigits(e.target.value).slice(0, 10))}
              onBlur={() => setTouched((s) => ({ ...s, phone: true }))}
              placeholder="10-digit mobile number"
            />
          </Field>
          <Field
            label="Aadhaar number (12 digits)"
            required
            hint={aadhaarDigits ? `${aadhaarDigits.length}/12` : '12 digits'}
            error={aadhaarError}
          >
            <input
              className="neu-input"
              required
              inputMode="numeric"
              value={form.aadhaar_id}
              onChange={(e) => f('aadhaar_id', e.target.value)}
              onBlur={() => setTouched((s) => ({ ...s, aadhaar_id: true }))}
              placeholder="XXXX XXXX XXXX"
              maxLength={14}
            />
          </Field>
          <Field
            label="ABHA ID (14 digits)"
            hint={abhaDigits ? `${abhaDigits.length}/14` : '14 digits'}
            error={abhaError}
          >
            <input
              className="neu-input"
              inputMode="numeric"
              value={form.abha_id}
              onChange={(e) => f('abha_id', e.target.value)}
              onBlur={() => setTouched((s) => ({ ...s, abha_id: true }))}
              placeholder="XX-XXXX-XXXX-XXXX"
              maxLength={17}
            />
          </Field>
        </div>
      </section>

      <section className="border-t border-[color:var(--border)] pt-5 mt-5">
        <div className="section-title mb-3">Contact &amp; Location</div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label={t('enroll.state')} required hint={form.phc ? 'Auto-filled from PHC' : undefined}>
            <select
              className="neu-input"
              required
              value={form.state}
              onChange={(e) => onStateChange(e.target.value)}
            >
              <option value="">{t('enroll.state_placeholder')}</option>
              {STATES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </Field>
          <Field label={t('enroll.district')} required hint={form.phc ? 'Auto-filled from PHC' : undefined}>
            <select
              className="neu-input"
              required
              disabled={!form.state}
              value={form.district}
              onChange={(e) => f('district', e.target.value)}
            >
              <option value="">
                {form.state ? t('enroll.district_placeholder') : t('enroll.district_locked')}
              </option>
              {districts.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </Field>
          <Field label="Taluk" required>
            <input
              className="neu-input"
              required
              value={form.taluk}
              onChange={(e) => f('taluk', e.target.value)}
              placeholder="Enter taluk"
            />
          </Field>
          <Field label="Village" required>
            <input
              className="neu-input"
              required
              value={form.village}
              onChange={(e) => f('village', e.target.value)}
              placeholder="Enter village or area"
            />
          </Field>
          <Field label="Gram Panchayat" required>
            <input
              className="neu-input"
              required
              value={form.gram_panchayat}
              onChange={(e) => f('gram_panchayat', e.target.value)}
              placeholder="Enter Gram Panchayat"
            />
          </Field>
          <Field label="House no">
            <input
              className="neu-input"
              value={form.house_no}
              onChange={(e) => f('house_no', e.target.value)}
              placeholder="House / door number"
            />
          </Field>
          <Field label="Referred by" required wide>
            <input
              className="neu-input"
              required
              value={form.referred_by}
              onChange={(e) => f('referred_by', e.target.value)}
              placeholder="ASHA / PHC name"
            />
          </Field>
        </div>
      </section>

      <section className="border-t border-[color:var(--border)] pt-5 mt-5">
        <div className="section-title mb-3">Household</div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="Household number">
            <input
              className="neu-input"
              value={form.household_number}
              onChange={(e) => f('household_number', e.target.value)}
              placeholder="Survey / household ID"
            />
          </Field>
          <Field label="Relation with head of family">
            <select
              className="neu-input"
              value={form.relation_to_head}
              onChange={(e) => f('relation_to_head', e.target.value)}
            >
              <option value="">Select relation</option>
              {RELATION_OPTIONS.map((r) => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
          </Field>
          <Field label="Head-of-family name">
            <input
              className="neu-input"
              value={form.head_of_family_name}
              onChange={(e) => f('head_of_family_name', e.target.value)}
              placeholder="Full name"
            />
          </Field>
          <Field label="Head-of-family phone" error={hofPhoneError}>
            <input
              className="neu-input"
              inputMode="numeric"
              maxLength={10}
              value={form.head_of_family_phone}
              onChange={(e) => f('head_of_family_phone', onlyDigits(e.target.value).slice(0, 10))}
              onBlur={() => setTouched((s) => ({ ...s, head_of_family_phone: true }))}
              placeholder="10-digit mobile number"
            />
          </Field>
        </div>
      </section>

      <div className="border-t border-[color:var(--border)] pt-5 mt-5">
        <label htmlFor="consent" className="flex items-start gap-2.5 text-sm t-soft cursor-pointer">
          <input
            type="checkbox"
            id="consent"
            checked={form.consent_given}
            onChange={(e) => f('consent_given', e.target.checked)}
            className="mt-0.5 accent-brand-600"
          />
          <span>
            {t('enroll.consent')} <span className="text-red-600">*</span>
          </span>
        </label>
      </div>

      {error && (
        <div className="text-sm text-red-700 border border-red-200 bg-red-50 rounded-md px-3 py-2 mt-4">
          {error}
        </div>
      )}

      <div className="flex justify-end mt-6">
        <button className="btn-primary inline-flex items-center gap-1.5" disabled={busy}>
          {busy ? '…' : (
            <>
              {t('enroll.submit')}
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

function Field({ label, required, wide, hint, error, children }) {
  return (
    <div className={wide ? 'md:col-span-2' : ''}>
      <label className="flex items-center justify-between gap-1 mb-1.5">
        <span className="text-xs font-medium t-soft">
          {label}
          {required && <span className="text-red-600 ml-0.5" aria-hidden>*</span>}
        </span>
        {hint && <span className="text-[11px] t-muted">{hint}</span>}
      </label>
      {children}
      {error && <p className="text-[11px] text-red-600 mt-1">{error}</p>}
    </div>
  );
}