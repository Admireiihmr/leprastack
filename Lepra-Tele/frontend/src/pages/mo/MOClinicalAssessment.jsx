import { useEffect, useState } from 'react';
import { api } from '../../lib/api';

const LESION_OPTIONS = [
  { v: 'single', l: 'Single' },
  { v: 'two_to_ten', l: '2-10' },
  { v: 'more_than_ten', l: '>10' },
  { v: 'pure_neuritic', l: 'Pure Neuritic' },
  { v: 'diffuse', l: 'Diffuse lesions' },
];

const STATUS_OPTIONS = [
  { v: 'new_untreated', l: 'New Untreated' },
  { v: 'continuation_mdt', l: 'Continuation of MDT' },
  { v: 'released', l: 'Released from treatment / control' },
  { v: 'defaulter', l: 'Defaulter / dropped out' },
  { v: 'relapse', l: 'Relapse' },
];

const WHO_OPTIONS = [
  { v: 'multibacillary', l: 'Multibacillary (MB)' },
  { v: 'paucibacillary', l: 'Paucibacillary (PB)' },
];

const SENSORY_OPTIONS = [
  { v: 'eye', l: 'Eye' },
  { v: 'hands', l: 'Hands' },
  { v: 'feet', l: 'Feet' },
  { v: 'none', l: 'None' },
];

const COMPLICATION_OPTIONS = [
  { v: 'type_1', l: 'Type-1 reaction' },
  { v: 'type_2', l: 'Type-2 reaction' },
  { v: 'neuritis', l: 'Neuritis' },
  { v: 'nfi', l: 'Nerve function impairment' },
  { v: 'ulcer', l: 'Ulcer' },
  { v: 'eye_involvement', l: 'Eye involvement' },
  { v: 'none', l: 'None' },
];

const NERVES = [
  { v: 'radial', l: 'Radial' },
  { v: 'ulnar', l: 'Ulnar' },
  { v: 'median', l: 'Median' },
  { v: 'lateral_popliteal', l: 'Lateral Popliteal' },
  { v: 'posterior_tibial', l: 'Posterior Tibial' },
];
const NERVE_STATES = [
  { v: 'none', l: 'None' },
  { v: 'tender', l: 'Tender' },
  { v: 'enlarged', l: 'Enlarged' },
  { v: 'not_examined', l: 'Not examined' },
];

function emptyNerveGrid() {
  // 5 nerves × 2 sides = 10 rows, default 'not_examined'
  const out = {};
  for (const n of NERVES) {
    out[`${n.v}_right`] = 'not_examined';
    out[`${n.v}_left`] = 'not_examined';
  }
  return out;
}

function nervesToList(grid) {
  return Object.entries(grid)
    .filter(([, state]) => state && state !== 'not_examined')
    .map(([k, state]) => {
      const [nerve, side] = k.split(/_(right|left)$/);
      return { nerve, side, state };
    });
}

function nervesFromList(list) {
  const grid = emptyNerveGrid();
  for (const f of list || []) {
    if (f?.nerve && f?.side) grid[`${f.nerve}_${f.side}`] = f.state || 'none';
  }
  return grid;
}

/** MO Clinical Assessment — the PDF1 "Teleconsultation" block.
 *  Required before the MO can send a final decision.
 */
export default function MOClinicalAssessment({ caseId, initial, onSaved, readOnly = false }) {
  const [confirmed, setConfirmed] = useState(initial?.confirmed_leprosy ?? null);
  const [lesion, setLesion] = useState(initial?.lesion_count || '');
  const [nerves, setNerves] = useState(() => nervesFromList(initial?.nerve_involvement));
  const [status, setStatus] = useState(initial?.clinical_status || '');
  const [who, setWho] = useState(initial?.who_classification || '');
  const [sensory, setSensory] = useState(initial?.sensory_loss || []);
  const [grade, setGrade] = useState(initial?.disability_grade ?? null);
  const [comps, setComps] = useState(initial?.complications || []);
  const [plan, setPlan] = useState(initial?.treatment_plan || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(Boolean(initial));
  const [open, setOpen] = useState(true);

  useEffect(() => {
    if (initial) {
      setConfirmed(initial.confirmed_leprosy ?? null);
      setLesion(initial.lesion_count || '');
      setNerves(nervesFromList(initial.nerve_involvement));
      setStatus(initial.clinical_status || '');
      setWho(initial.who_classification || '');
      setSensory(initial.sensory_loss || []);
      setGrade(initial.disability_grade ?? null);
      setComps(initial.complications || []);
      setPlan(initial.treatment_plan || '');
      setSaved(true);
    }
  }, [initial]);

  const toggle = (arr, setArr, v, exclusive = 'none') => {
    if (v === exclusive) {
      setArr(arr.includes(v) ? [] : [v]);
      return;
    }
    setArr(
      arr.includes(v)
        ? arr.filter((x) => x !== v)
        : [...arr.filter((x) => x !== exclusive), v],
    );
  };

  const save = async () => {
    setError(null);
    if (confirmed === null) {
      setError('Please indicate whether leprosy is confirmed.');
      return;
    }
    setBusy(true);
    try {
      const payload = {
        confirmed_leprosy: confirmed,
        lesion_count: lesion || null,
        nerve_involvement: nervesToList(nerves),
        clinical_status: status || null,
        who_classification: who || null,
        sensory_loss: sensory,
        disability_grade: grade,
        complications: comps,
        treatment_plan: plan || null,
      };
      await api(`/cases/${caseId}/clinical-assessment`, {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      setSaved(true);
      onSaved?.(payload);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card-elev">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex flex-wrap items-baseline justify-between gap-2 mb-4 text-left"
        aria-expanded={open}
      >
        <div>
          <div className="section-title">Post-consultation</div>
          <h3 className="text-lg font-semibold t-ink">MO clinical assessment</h3>
          <p className="text-xs t-muted mt-1">Save this before sending the decision.</p>
        </div>
        <span className="flex items-center gap-2 shrink-0">
          {saved && <span className="pill-green">Saved</span>}
          <svg className={`transition-transform duration-200 t-muted ${open ? 'rotate-180' : ''}`} width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 9l6 6 6-6" /></svg>
        </span>
      </button>

      {open && (
      <fieldset disabled={readOnly} className="space-y-5 border-0 p-0 m-0 min-w-0 disabled:opacity-80">
        {readOnly && (
          <div className="rounded-md border border-amber-300 bg-amber-50 px-3.5 py-2.5 text-sm text-amber-800">
            <span className="font-semibold">Read-only.</span> This session has expired — the assessment cannot be changed.
          </div>
        )}
        {/* Confirmed Y/N */}
        <Row num={1} label="Confirmed case of leprosy" required>
          <YesNo value={confirmed} onChange={setConfirmed} />
        </Row>

        {confirmed === true && (
        <>
        {/* Lesion count */}
        <Row num={2} label="No. of skin lesions">
          <RadioRow value={lesion} onChange={setLesion} options={LESION_OPTIONS} />
        </Row>

        {/* Nerve involvement grid */}
        <div>
          <div className="mb-2"><QHeading num={3} label="Nerve involvement" /></div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs min-w-[560px]">
              <thead className="text-[10px] uppercase tracking-wider t-muted">
                <tr className="border-b border-[color:var(--border)]">
                  <th className="text-left font-semibold px-3 py-2">Nerve</th>
                  <th className="text-left font-semibold px-3 py-2">Right</th>
                  <th className="text-left font-semibold px-3 py-2">Left</th>
                </tr>
              </thead>
              <tbody>
                {NERVES.map((n) => (
                  <tr key={n.v} className="border-b border-[color:var(--border)] last:border-0">
                    <td className="px-3 py-2 t-ink font-medium">{n.l}</td>
                    <td className="px-3 py-2">
                      <select
                        className="neu-input !py-1 text-xs"
                        value={nerves[`${n.v}_right`] || 'not_examined'}
                        onChange={(e) => setNerves((g) => ({ ...g, [`${n.v}_right`]: e.target.value }))}
                      >
                        {NERVE_STATES.map((ns) => <option key={ns.v} value={ns.v}>{ns.l}</option>)}
                      </select>
                    </td>
                    <td className="px-3 py-2">
                      <select
                        className="neu-input !py-1 text-xs"
                        value={nerves[`${n.v}_left`] || 'not_examined'}
                        onChange={(e) => setNerves((g) => ({ ...g, [`${n.v}_left`]: e.target.value }))}
                      >
                        {NERVE_STATES.map((ns) => <option key={ns.v} value={ns.v}>{ns.l}</option>)}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Status + WHO classification */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          <Row num={4} label="Status of case" stacked>
            <RadioStack value={status} onChange={setStatus} options={STATUS_OPTIONS} />
          </Row>
          <Row num={5} label="WHO classification" stacked>
            <RadioStack value={who} onChange={setWho} options={WHO_OPTIONS} />
          </Row>
        </div>

        {/* Sensory loss + Disability grade */}
        <Row num={6} label="Sensory loss">
          <ChipMulti values={sensory} options={SENSORY_OPTIONS} onToggle={(v) => toggle(sensory, setSensory, v, 'none')} />
        </Row>

        <Row num={7} label="Disability grade">
          <div className="inline-flex rounded-md border border-[color:var(--border)] overflow-hidden">
            {[0, 1, 2].map((g, i) => {
              const selected = grade === g;
              return (
                <button
                  key={g}
                  type="button"
                  onClick={() => setGrade(g)}
                  className={
                    (selected
                      ? 'bg-brand-600 text-white'
                      : 'bg-[color:var(--surface)] t-soft hover:bg-[color:var(--surface-2)]') +
                    ' px-4 py-1.5 text-sm font-medium' +
                    (i !== 0 ? ' border-l border-[color:var(--border)]' : '')
                  }
                >
                  Grade {g}
                </button>
              );
            })}
          </div>
        </Row>

        {/* Complications */}
        <Row num={8} label="Complications">
          <ChipMulti values={comps} options={COMPLICATION_OPTIONS} onToggle={(v) => toggle(comps, setComps, v, 'none')} />
        </Row>

        {/* Treatment plan */}
        <div>
          <div className="mb-1.5"><QHeading num={9} label="Treatment plan" /></div>
          <textarea
            className="neu-input"
            rows={3}
            value={plan}
            onChange={(e) => setPlan(e.target.value)}
            placeholder="MDT regimen, dose, duration, follow-up plan…"
          />
        </div>
        </>
        )}

        {error && (
          <div className="text-sm text-red-700 border border-red-200 bg-red-50 rounded-md px-3 py-2">{error}</div>
        )}

        <div className="flex justify-end">
          <button type="button" onClick={save} disabled={busy} className="btn-primary">
            {busy ? 'Saving…' : saved ? 'Update assessment' : 'Save assessment'}
          </button>
        </div>
      </fieldset>
      )}
    </section>
  );
}

function NumBadge({ n }) {
  return (
    <span className="w-5 h-5 shrink-0 grid place-items-center rounded-md bg-brand-50 text-brand-700 text-[11px] font-bold">
      {n}
    </span>
  );
}

// Prominent, numbered question heading used across the assessment.
function QHeading({ num, label, required }) {
  return (
    <div className="flex items-center gap-2 text-sm font-bold text-brand-700">
      {num != null && <NumBadge n={num} />}
      <span>{label}{required && <span className="text-red-600 ml-0.5">*</span>}</span>
    </div>
  );
}

function Row({ label, required, stacked, num, children }) {
  return (
    <div className={stacked ? '' : 'flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3'}>
      <div className={stacked ? 'mb-2' : 'flex-1 min-w-0'}>
        <QHeading num={num} label={label} required={required} />
      </div>
      <div className={stacked ? '' : 'shrink-0'}>{children}</div>
    </div>
  );
}

function YesNo({ value, onChange }) {
  return (
    <div className="inline-flex rounded-md border border-[color:var(--border)] overflow-hidden">
      {[
        { v: true, l: 'Yes' },
        { v: false, l: 'No' },
      ].map((opt, i) => {
        const selected = value === opt.v;
        return (
          <button
            key={String(opt.v)}
            type="button"
            onClick={() => onChange(opt.v)}
            className={
              (selected
                ? 'bg-brand-600 text-white'
                : 'bg-[color:var(--surface)] t-soft hover:bg-[color:var(--surface-2)]') +
              ' px-4 py-1.5 text-sm font-medium' +
              (i !== 0 ? ' border-l border-[color:var(--border)]' : '')
            }
          >
            {opt.l}
          </button>
        );
      })}
    </div>
  );
}

function RadioRow({ value, onChange, options }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const selected = value === o.v;
        return (
          <button
            key={o.v}
            type="button"
            onClick={() => onChange(o.v)}
            className={
              selected
                ? 'px-3 py-1.5 rounded-md text-sm font-medium border bg-brand-50 text-brand-700 border-brand-300'
                : 'px-3 py-1.5 rounded-md text-sm font-medium border bg-[color:var(--surface)] t-soft border-[color:var(--border)] hover:border-[color:var(--border-strong)]'
            }
          >
            {o.l}
          </button>
        );
      })}
    </div>
  );
}

function RadioStack({ value, onChange, options }) {
  return (
    <div className="space-y-1.5">
      {options.map((o) => {
        const selected = value === o.v;
        return (
          <label
            key={o.v}
            className={`flex items-center gap-2.5 px-3 py-2 rounded-md border cursor-pointer text-sm ${
              selected ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-[color:var(--border)] t-soft'
            }`}
          >
            <span
              className="w-4 h-4 rounded-full border-2 grid place-items-center"
              style={{ borderColor: selected ? 'var(--brand)' : 'var(--border-strong)' }}
            >
              {selected && <span className="w-2 h-2 rounded-full" style={{ background: 'var(--brand)' }} />}
            </span>
            <input type="radio" checked={selected} onChange={() => onChange(o.v)} className="sr-only" />
            <span>{o.l}</span>
          </label>
        );
      })}
    </div>
  );
}

function ChipMulti({ values, options, onToggle }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const selected = values.includes(o.v);
        return (
          <button
            key={o.v}
            type="button"
            onClick={() => onToggle(o.v)}
            className={
              selected
                ? 'px-3 py-1.5 rounded-md text-sm font-medium border bg-brand-50 text-brand-700 border-brand-300'
                : 'px-3 py-1.5 rounded-md text-sm font-medium border bg-[color:var(--surface)] t-soft border-[color:var(--border)] hover:border-[color:var(--border-strong)]'
            }
          >
            {o.l}
          </button>
        );
      })}
    </div>
  );
}
