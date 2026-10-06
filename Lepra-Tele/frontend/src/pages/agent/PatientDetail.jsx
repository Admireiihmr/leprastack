import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api, downloadAuthFile } from '../../lib/api';
import { formatId, idForFilename } from '../../lib/ids';

const TRIAGE_META = {
  rule_out:       { label: 'Not affected',    cls: 'pill-green' },
  alternative_dx: { label: 'Alternative Dx',  cls: 'pill-amber' },
  escalate:       { label: 'Affected · MO',   cls: 'pill-red'   },
};

const STATUS_LABELS = {
  intake:           'Intake',
  triaged:          'Triaged',
  awaiting_mo:      'Awaiting MO',
  scheduled:        'Scheduled',
  in_consult:       'In consult',
  closed_remote:    'Closed — community',
  referred:         'Referred',
  closed_alt_dx:    'Closed — alt dx',
  closed_rule_out:  'Closed — rule out',
};

function relTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return d.toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric' });
}

function DataRow({ label, value }) {
  if (!value && value !== 0) return null;
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-wider font-semibold t-muted">{label}</span>
      <span className="text-sm t-ink font-medium">{value}</span>
    </div>
  );
}

export default function PatientDetail() {
  const { id } = useParams();
  const [patient, setPatient] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api(`/patients/${id}`)
      .then(setPatient)
      .catch((e) => setError(e?.message || 'Failed to load patient'));
  }, [id]);

  if (error) {
    return (
      <div className="card-elev">
        <p className="text-sm text-red-700">{error}</p>
        <Link to="/agent/patients" className="text-sm link mt-2 inline-block">← Back to patients</Link>
      </div>
    );
  }

  if (!patient) {
    return (
      <div className="space-y-5 animate-pulse">
        <div className="h-6 w-40 bg-[color:var(--surface-2)] rounded-md" />
        <div className="h-8 w-64 bg-[color:var(--surface-2)] rounded-md" />
        <div className="h-40 bg-[color:var(--surface-2)] rounded-xl border border-[color:var(--border)]" />
        <div className="h-40 bg-[color:var(--surface-2)] rounded-xl border border-[color:var(--border)]" />
      </div>
    );
  }

  const cases = patient.cases || [];
  const latestCase = cases[0];
  const triageMeta = latestCase?.triage_outcome ? TRIAGE_META[latestCase.triage_outcome] : null;

  return (
    <div className="space-y-5">
      {/* Back + header */}
      <div>
        <Link to="/agent/patients" className="text-xs link inline-flex items-center gap-1 mb-3">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
          Patients
        </Link>
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <div className="flex items-center gap-2.5 flex-wrap">
              <h1 className="text-2xl font-semibold tracking-tight t-ink">{patient.name}</h1>
              {triageMeta && (
                <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold border border-transparent ${triageMeta.cls}`}>
                  {triageMeta.label}
                </span>
              )}
            </div>
            <p className="text-xs t-muted mt-0.5 font-mono tracking-wide">{formatId(patient.id)}</p>
          </div>
          {latestCase && (
            <button
              className="btn-ghost shrink-0 text-xs"
              onClick={() => downloadAuthFile(`/cases/${latestCase.id}/intake.pdf`, `intake-${idForFilename(latestCase.id)}.pdf`)}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mr-1.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              Download report
            </button>
          )}
        </div>
      </div>

      {/* Demographics + Programme context */}
      <section className="grid grid-cols-1 md:grid-cols-2 gap-5">
        <div className="card-elev">
          <h2 className="text-sm font-semibold t-ink mb-3">Demographics</h2>
          <div className="grid grid-cols-2 gap-x-4 gap-y-3">
            <DataRow label="Age" value={patient.age ? `${patient.age} yrs` : null} />
            <DataRow label="Sex" value={patient.sex ? patient.sex.charAt(0).toUpperCase() + patient.sex.slice(1) : null} />
            <DataRow label="Phone" value={patient.phone} />
            <DataRow label="Referred by" value={patient.referred_by} />
            <DataRow label="Aadhaar" value={patient.aadhaar_id} />
            <DataRow label="ABHA" value={patient.abha_id} />
          </div>
        </div>

        <div className="card-elev">
          <h2 className="text-sm font-semibold t-ink mb-3">Programme context</h2>
          <div className="grid grid-cols-2 gap-x-4 gap-y-3">
            <DataRow label="PHC / CHC" value={patient.phc} />
            <DataRow label="Supervisor" value={patient.supervisor} />
            <DataRow label="CHW" value={patient.chw} />
            <DataRow label="Registered" value={patient.created_at ? relTime(patient.created_at) : null} />
          </div>
        </div>
      </section>

      {/* Location */}
      <section className="card-elev">
        <h2 className="text-sm font-semibold t-ink mb-3">Location</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-x-4 gap-y-3">
          <DataRow label="House no." value={patient.house_no} />
          <DataRow label="Village" value={patient.village} />
          <DataRow label="Gram Panchayat" value={patient.gram_panchayat} />
          <DataRow label="Taluk" value={patient.taluk} />
          <DataRow label="District" value={patient.district} />
          <DataRow label="State" value={patient.state} />
        </div>
      </section>

      {/* Household */}
      {(patient.household_number || patient.head_of_family_name) && (
        <section className="card-elev">
          <h2 className="text-sm font-semibold t-ink mb-3">Household</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-3">
            <DataRow label="Household no." value={patient.household_number} />
            <DataRow label="Head of family" value={patient.head_of_family_name} />
            <DataRow label="HoF phone" value={patient.head_of_family_phone} />
            <DataRow label="Relation" value={patient.relation_to_head?.replace(/_/g, ' ')} />
          </div>
        </section>
      )}

      {/* Case history */}
      <section className="card-elev !p-0 overflow-hidden">
        <div className="px-5 py-4 border-b border-[color:var(--border)]">
          <h2 className="text-base font-semibold t-ink">Case history</h2>
          <p className="text-xs t-muted mt-0.5">{cases.length} case{cases.length !== 1 ? 's' : ''} on record</p>
        </div>
        {cases.length === 0 ? (
          <div className="text-sm t-muted text-center py-8">No cases recorded yet.</div>
        ) : (
          <ul className="divide-y divide-[color:var(--border-cool)]">
            {cases.map((c) => {
              const tm = c.triage_outcome ? TRIAGE_META[c.triage_outcome] : null;
              return (
                <li key={c.id} className="px-5 py-3.5 flex items-center justify-between gap-4 hover:bg-[color:var(--surface-2)]">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono text-xs t-soft">{formatId(c.id)}</span>
                      {tm && (
                        <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-semibold border border-transparent ${tm.cls}`}>
                          {tm.label}
                        </span>
                      )}
                      <span className="text-xs t-muted">{STATUS_LABELS[c.status] || c.status}</span>
                    </div>
                    <div className="text-xs t-muted mt-0.5">{relTime(c.created_at)}</div>
                  </div>
                  <button
                    className="btn-ghost !p-1.5 shrink-0"
                    title="Download intake PDF"
                    onClick={() => downloadAuthFile(`/cases/${c.id}/intake.pdf`, `intake-${idForFilename(c.id)}.pdf`)}
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
