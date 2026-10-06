import { useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api, downloadAuthFile, uploadFile } from '../../lib/api';
import { useAuth } from '../../context/AuthContext';
import MeetingDetails from '../../components/MeetingDetails';
import MOClinicalAssessment from './MOClinicalAssessment';
import { meetingPhase } from '../../lib/meetingPhase';
import { formatId, idForFilename } from '../../lib/ids';
import Banner from '../../components/Banner';

const defaultWhen = () => {
  const d = new Date(Date.now() + 60 * 60 * 1000);
  d.setSeconds(0, 0);
  return d.toISOString().slice(0, 16);
};

export default function CaseReview() {
  const { id } = useParams();
  const nav = useNavigate();
  const { user } = useAuth();
  const [c, setC] = useState(null);
  const [decision, setDecision] = useState('close_remote');
  const [rx, setRx] = useState('');
  const [referral, setReferral] = useState('');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [assessmentSaved, setAssessmentSaved] = useState(false);
  const [decisionSaved, setDecisionSaved] = useState(false);
  const [decisionError, setDecisionError] = useState(null);
  const [appointmentId, setAppointmentId] = useState(null);
  const [appointment, setAppointment] = useState(null);
  const [when, setWhen] = useState(defaultWhen());
  const [duration, setDuration] = useState(20);
  const [schedBusy, setSchedBusy] = useState(false);
  const [schedError, setSchedError] = useState(null);

  const refresh = () => {
    api(`/cases/${id}`).then((d) => {
      setC(d);
      setAssessmentSaved(Boolean(d?.clinical_assessment));
    });
    api('/appointments/mine').then((appts) => {
      const matches = (appts || []).filter((x) => x.case_id === id);
      const latest = matches.sort(
        (a, b) => new Date(b.scheduled_at) - new Date(a.scheduled_at),
      )[0];
      if (latest) {
        setAppointmentId(latest.id);
        setAppointment(latest);
      } else {
        setAppointmentId(null);
        setAppointment(null);
      }
    });
  };

  const [, setNowTick] = useState(0);

  useEffect(() => {
    refresh();
    const handle = setInterval(() => setNowTick((t) => t + 1), 30_000);
    return () => clearInterval(handle);
  }, [id]);

  const schedule = async () => {
    setSchedBusy(true);
    setSchedError(null);
    try {
      const appt = await api('/appointments', {
        method: 'POST',
        body: JSON.stringify({
          case_id: id,
          mo_uid: user.uid,
          scheduled_at: new Date(when).toISOString(),
          duration_minutes: duration,
        }),
      });
      setAppointment(appt);
      setAppointmentId(appt.id);
      refresh();
    } catch (err) {
      setSchedError(err.message);
    } finally {
      setSchedBusy(false);
    }
  };

  const submit = async () => {
    setBusy(true);
    setDecisionError(null);
    try {
      await api(`/cases/${id}/decision`, {
        method: 'POST',
        body: JSON.stringify({
          decision,
          // close_remote uses the prescription box; alt_dx uses the treatment-notes
          // box - both bind to `rx`. refer uses the referral box.
          prescription: decision === 'refer' ? null : rx,
          referral_note: decision === 'refer' ? referral : null,
          notes,
        }),
      });
      // Decision is now saved server-side (and its PDF generated) independently
      // of WhatsApp. Stay on the page and refresh so the MO can download the
      // finalised decision PDF.
      setDecisionSaved(true);
      refresh();
    } catch (err) {
      setDecisionError(err.message || 'Could not save the decision. Try again.');
    } finally {
      setBusy(false);
    }
  };

  const [docBusy, setDocBusy] = useState(false);
  const [docError, setDocError] = useState(null);
  const uploadDoc = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setDocBusy(true);
    setDocError(null);
    try {
      await uploadFile(`/cases/${id}/documents`, file);
      refresh();
    } catch (err) {
      setDocError(err.message || 'Upload failed.');
    } finally {
      setDocBusy(false);
    }
  };

  if (!c) return <p className="t-muted">Loading…</p>;
  const screen = c.screening || {};
  const hist = c.history || {};
  const postConsultDocs = c.post_consult_docs || [];
  const recordings = c.recordings || [];
  // Once the consult slot has passed, the case is read-only - the MO can view
  // everything but cannot update the assessment or send a new decision.
  const sessionExpired = appointment
    ? meetingPhase(appointment.scheduled_at, appointment.duration_minutes || 30).phase === 'expired'
    : false;

  return (
    <div>
      {/* Page header */}
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4 mb-6">
        <div className="flex items-start gap-3">
          <button onClick={() => nav('/mo')} className="btn-ghost !px-2.5 !py-2" aria-label="Back">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M19 12H5" /><path d="M12 19l-7-7 7-7" />
            </svg>
          </button>
          <div>
            <div className="section-title">MO · Case Review</div>
            <h1 className="text-2xl font-semibold tracking-tight t-ink">{c.patient_name}</h1>
            <p className="text-sm t-muted mt-1">
              <span className="font-mono">{formatId(c.id)}</span> · Submitted {fmtDateTime(c.created_at)}
            </p>
          </div>
        </div>
      </div>

      {sessionExpired && (
        <div className="mb-5 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 flex items-start gap-3">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-amber-600 shrink-0 mt-0.5"><circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" /></svg>
          <div>
            <div className="text-sm font-semibold text-amber-800">Session expired - read only</div>
            <p className="text-xs text-amber-700 mt-0.5">
              The consultation slot has passed. You can view this case but cannot update the assessment or send a decision.
            </p>
          </div>
        </div>
      )}

      <div className="space-y-5">
        {/* AGENT-COLLECTED INTAKE - collapsible to reduce scroll */}
        <Collapsible title="Intake by field agent" subtitle="Patient record" meta={c.agent_name ? `Submitted by ${c.agent_name}` : null}>

          {/* Demographics */}
          <SectionLabel>Demographics</SectionLabel>
          <DataGrid>
            <DataRow label="Full name" value={c.patient_name} />
            <DataRow label="Age" value={c.patient_age ? `${c.patient_age} years` : null} />
            <DataRow label="Sex" value={cap(c.patient_sex)} />
            <DataRow label="Phone" value={c.patient_phone} mono />
          </DataGrid>

          {/* Programme context */}
          <Divider />
          <SectionLabel>Programme context</SectionLabel>
          <DataGrid>
            <DataRow label="PHC / CHC" value={c.patient_phc} />
          </DataGrid>

          {/* Location & IDs */}
          <Divider />
          <SectionLabel>Location & identifiers</SectionLabel>
          <DataGrid>
            <DataRow label="House no" value={c.patient_house_no} />
            <DataRow label="Village" value={c.patient_village} />
            <DataRow label="Gram Panchayat" value={c.patient_gram_panchayat} />
            <DataRow label="District" value={c.patient_district} />
            <DataRow label="State" value={c.patient_state} />
            <DataRow label="Aadhaar" value={c.patient_aadhaar_id} mono />
            <DataRow label="ABHA" value={c.patient_abha_id} mono />
            <DataRow label="Referred by" value={c.patient_referred_by} />
          </DataGrid>

          {/* Household */}
          <Divider />
          <SectionLabel>Household</SectionLabel>
          <DataGrid>
            <DataRow label="Household number" value={c.patient_household_number} />
            <DataRow label="Relation to head" value={prettyRelation(c.patient_relation_to_head)} />
            <DataRow label="Head-of-family name" value={c.patient_head_of_family_name} />
            <DataRow label="Head-of-family phone" value={c.patient_head_of_family_phone} mono />
          </DataGrid>

          {/* Medical history */}
          <Divider />
          <SectionLabel>Medical history</SectionLabel>
          <div className="space-y-3">
            <div>
              <div className="text-[11px] uppercase tracking-wider t-muted font-semibold mb-2">Chronic conditions</div>
              {Array.isArray(hist.chronic_conditions) && hist.chronic_conditions.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {hist.chronic_conditions.map((cc, i) => (
                    <span key={i} className="pill-brand">{cc}</span>
                  ))}
                </div>
              ) : (
                <p className="text-sm t-muted">None reported</p>
              )}
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-wider t-muted font-semibold mb-1">Past visits / notes</div>
              <p className="text-sm t-ink whitespace-pre-wrap">{hist.past_visits_notes || <span className="t-muted">—</span>}</p>
            </div>
            {Array.isArray(hist.prior_prescriptions_urls) && hist.prior_prescriptions_urls.length > 0 && (
              <div>
                <div className="text-[11px] uppercase tracking-wider t-muted font-semibold mb-2">Prior prescriptions</div>
                <div className="grid grid-cols-4 sm:grid-cols-6 gap-2">
                  {hist.prior_prescriptions_urls.map((u, i) => (
                    <a key={i} href={u} target="_blank" rel="noreferrer" className="aspect-square rounded-md overflow-hidden block border border-[color:var(--border-cool)] hover:border-[color:var(--border-strong)]">
                      <img src={u} alt="" className="w-full h-full object-cover" />
                    </a>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Screening event context */}
          {(screen.screened_at || screen.geolocation) && (
            <>
              <Divider />
              <SectionLabel>Screening event</SectionLabel>
              <DataGrid>
                <DataRow label="Date of screening" value={screen.screened_at ? fmtDateTime(screen.screened_at) : null} />
                <DataRow
                  label="GPS"
                  value={screen.geolocation ? (
                    <a
                      href={`https://maps.google.com/?q=${screen.geolocation.lat},${screen.geolocation.lng}`}
                      target="_blank" rel="noreferrer"
                      className="link font-mono text-xs"
                    >
                      {screen.geolocation.lat?.toFixed?.(5)}, {screen.geolocation.lng?.toFixed?.(5)}
                      {screen.geolocation.accuracy != null && ` · ±${Math.round(screen.geolocation.accuracy)}m`}
                    </a>
                  ) : null}
                />
              </DataGrid>
            </>
          )}

          {/* Symptom screening - the 11-question leprosy checklist */}
          {screen.symptoms && Object.keys(screen.symptoms).length > 0 && (
            <>
              <Divider />
              <SectionLabel>Symptom screening</SectionLabel>
              <DataGrid>
                {LEPROSY_SYMPTOMS.map(([label, key], i) => (
                  <YesNoRow key={key} label={`${i + 1}. ${label}`} value={screen.symptoms[key]} />
                ))}
              </DataGrid>
            </>
          )}

          {/* Symptom details - Duration and Household Contact */}
          {(screen.duration_months !== undefined || screen.family_history_leprosy !== undefined) && (
            <>
              <Divider />
              <SectionLabel>Symptom Details</SectionLabel>
              <DataGrid>
                {screen.duration_months !== undefined && screen.duration_months !== null && (
                  <DataRow label="Duration of symptoms" value={`${screen.duration_months} months`} />
                )}
                {screen.family_history_leprosy !== undefined && screen.family_history_leprosy !== null && (
                  <DataRow label="Household contact with leprosy" value={screen.family_history_leprosy ? 'Yes' : 'No'} />
                )}
              </DataGrid>
            </>
          )}

          {screen.notes && (
            <div className="mt-4">
              <div className="text-[11px] uppercase tracking-wider t-muted font-semibold mb-1">Agent notes</div>
              <p className="text-sm t-ink whitespace-pre-wrap">{screen.notes}</p>
            </div>
          )}

          {/* Screening images */}
          {Array.isArray(screen.image_urls) && screen.image_urls.length > 0 && (
            <>
              <Divider />
              <SectionLabel>Screening images ({screen.image_urls.length})</SectionLabel>
              <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-2">
                {screen.image_urls.map((u, i) => (
                  <a key={i} href={u} target="_blank" rel="noreferrer" className="aspect-square rounded-md overflow-hidden block border border-[color:var(--border-cool)] hover:border-[color:var(--border-strong)]">
                    <img src={u} alt="" className="w-full h-full object-cover" />
                  </a>
                ))}
              </div>
            </>
          )}

          {/* Lab investigations (from screening or history) */}
          {(() => {
            const labs = [
              ...(Array.isArray(screen.lab_urls) ? screen.lab_urls : []),
              ...(Array.isArray(hist.prior_labs_urls) ? hist.prior_labs_urls : []),
            ];
            if (labs.length === 0) return null;
            return (
              <>
                <Divider />
                <SectionLabel>Lab investigations ({labs.length})</SectionLabel>
                <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-2">
                  {labs.map((u, i) => (
                    <a key={i} href={u} target="_blank" rel="noreferrer" className="aspect-square rounded-md overflow-hidden block border border-[color:var(--border-cool)] hover:border-[color:var(--border-strong)]">
                      <img src={u} alt="" className="w-full h-full object-cover" />
                    </a>
                  ))}
                </div>
              </>
            );
          })()}
        </Collapsible>

        {/* TELE-CONSULT - moved after intake as requested */}
        <TeleConsultBlock
          caseId={c.id}
          onRecorded={refresh}
          appointment={appointment}
          when={when}
          setWhen={setWhen}
          duration={duration}
          setDuration={setDuration}
          schedule={schedule}
          schedBusy={schedBusy}
          schedError={schedError}
        />

        {/* MO Clinical Assessment - required before decision */}
        <MOClinicalAssessment
          caseId={c.id}
          initial={c.clinical_assessment || null}
          onSaved={() => setAssessmentSaved(true)}
          readOnly={sessionExpired}
        />

        {/* MO Decision */}
        <section className="card-elev">
          <div className="mb-4">
            <div className="section-title">Action</div>
            <h3 className="text-lg font-semibold t-ink">MO decision</h3>
          </div>
          <div className="space-y-2.5">
            <DecisionRadio
              checked={decision === 'close_remote'}
              onChange={() => setDecision('close_remote')}
              title="Rule-out"
              subtitle="Home care, recall in 4–6 weeks"
              tone="good"
            />
            <DecisionRadio
              checked={decision === 'alt_dx'}
              onChange={() => setDecision('alt_dx')}
              title="Alternative Diagnosis"
              subtitle="Provide treatment & close"
              tone="warn"
            />
            <DecisionRadio
              checked={decision === 'refer'}
              onChange={() => setDecision('refer')}
              title="Escalate"
              subtitle="Refer to PHC / CHC / Hospital"
              tone="bad"
            />
          </div>

          {decision === 'close_remote' ? (
            <div className="mt-4">
              <label className="label">Prescription / care plan</label>
              <textarea className="neu-input" rows={3} value={rx} onChange={(e) => setRx(e.target.value)} placeholder="MDT-MB regimen, dose, duration…" />
            </div>
          ) : decision === 'refer' ? (
            <div className="mt-4">
              <label className="label">Referral note (optional)</label>
              <textarea className="neu-input" rows={3} value={referral} onChange={(e) => setReferral(e.target.value)} placeholder="Add referral notes or instructions…" />
            </div>
          ) : (
            <div className="mt-4">
              <label className="label">Treatment notes</label>
              <textarea className="neu-input" rows={3} value={rx} onChange={(e) => setRx(e.target.value)} placeholder="Recommended treatment for alternative diagnosis…" />
            </div>
          )}

          <div className="mt-3">
            <label className="label">Internal notes</label>
            <textarea className="neu-input" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Add notes for the audit log…" />
          </div>
        </section>

        {/* Post-consultation documents + recordings */}
        <section className="card-elev">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
            <div>
              <div className="section-title !mb-1">Post-consultation</div>
              <p className="text-xs t-muted">Upload reports/prescriptions after the consult - stored in the patient folder.</p>
            </div>
            <label className={`btn-ghost cursor-pointer ${docBusy ? 'opacity-60 pointer-events-none' : ''}`}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" /></svg>
              {docBusy ? 'Uploading…' : 'Upload document'}
              <input type="file" accept="application/pdf,image/*" className="hidden" onChange={uploadDoc} />
            </label>
          </div>
          {docError && <Banner kind="error" className="mb-3">{docError}</Banner>}
          {(postConsultDocs.length > 0 || recordings.length > 0) ? (
            <ul className="space-y-1.5">
              {postConsultDocs.map((d, i) => (
                <li key={`doc-${i}`} className="flex items-center gap-2 text-sm">
                  <span className="t-muted">📄</span>
                  <a href={d.url} target="_blank" rel="noreferrer" className="link truncate">{d.name || `Document ${i + 1}`}</a>
                </li>
              ))}
              {recordings.map((r, i) => (
                <li key={`rec-${i}`} className="flex items-center gap-2 text-sm">
                  <span className="t-muted">🎥</span>
                  <a href={r.url} target="_blank" rel="noreferrer" className="link truncate">{r.filename || `Recording ${i + 1}`}</a>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs t-muted">No documents or recordings yet.</p>
          )}
        </section>

        {/* Action bar */}
        <section className="card-elev">
          {decisionSaved && (
            <Banner kind="success" className="mb-3">
              <span className="font-semibold">Decision saved.</span> The decision PDF has been generated and stored.
              The patient is notified via WhatsApp automatically - delivery does not affect the saved record. You can download the PDF below.
            </Banner>
          )}
          {decisionError && (
            <Banner kind="error" className="mb-3">{decisionError}</Banner>
          )}
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
            <div className="text-xs t-muted">
              {sessionExpired
                ? 'This session has expired - the decision can no longer be changed.'
                : !assessmentSaved
                  ? 'Save the clinical assessment above before saving the decision.'
                  : decisionSaved
                    ? 'Decision is saved independently of WhatsApp. Download it any time below.'
                    : 'Saving records the decision and generates its PDF, then notifies the patient via WhatsApp.'}
            </div>
            <div className="flex flex-col sm:flex-row sm:flex-wrap gap-2 sm:justify-end">
              <button
                type="button"
                className="btn-ghost w-full sm:w-auto"
                onClick={() => downloadAuthFile(`/cases/${c.id}/intake.pdf`, `agent-report-${idForFilename(c.id)}.pdf`)}
                title="Download the agent report"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
                Agent Report
              </button>
              <button
                type="button"
                className="btn-ghost w-full sm:w-auto"
                onClick={() => downloadAuthFile(`/cases/${c.id}/decision.pdf`, `mo-report-${idForFilename(c.id)}.pdf`)}
                disabled={!assessmentSaved}
                title={assessmentSaved ? 'Download the MO report' : 'Save the clinical assessment first'}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
                MO Report
              </button>
              {decisionSaved ? (
                <button type="button" className="btn-primary w-full sm:w-auto" onClick={() => nav('/mo')}>
                  Back to queue
                </button>
              ) : (
                <button
                  type="button"
                  className="btn-primary w-full sm:w-auto"
                  disabled={busy || !assessmentSaved || sessionExpired}
                  onClick={submit}
                  title={sessionExpired ? 'Session expired - read only' : !assessmentSaved ? 'Save the clinical assessment first' : undefined}
                >
                  {busy ? 'Saving…' : 'Save decision & notify'}
                </button>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

const TONE = {
  good: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  warn: 'bg-amber-50 text-amber-800 border-amber-200',
  bad: 'bg-red-50 text-red-700 border-red-200',
  muted: 'bg-[color:var(--surface-2)] t-soft border-[color:var(--border-cool)]',
};

function SectionLabel({ children }) {
  return <div className="text-[11px] uppercase tracking-[0.12em] t-muted font-semibold mb-3">{children}</div>;
}

function Divider() {
  return <div className="border-t border-[color:var(--border-cool)] my-5" />;
}

// Collapsible card - click the header to expand/collapse, to tame the long page.
function Collapsible({ title, subtitle, meta, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="card-elev !p-0 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-3 px-5 sm:px-6 py-4 text-left hover:bg-[color:var(--surface-2)] transition-colors"
        aria-expanded={open}
      >
        <div className="min-w-0">
          <div className="section-title !mb-1">{title}</div>
          {subtitle && <h3 className="text-lg font-semibold t-ink">{subtitle}</h3>}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {meta && <span className="text-xs t-muted hidden sm:inline">{meta}</span>}
          <svg className={`transition-transform duration-200 t-muted ${open ? 'rotate-180' : ''}`} width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 9l6 6 6-6" /></svg>
        </div>
      </button>
      {open && <div className="px-5 sm:px-6 pb-6">{children}</div>}
    </section>
  );
}

function DataGrid({ children }) {
  return <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-3">{children}</dl>;
}

function DataRow({ label, value, mono }) {
  const empty = value == null || value === '';
  return (
    <div className="min-w-0">
      <dt className="text-[11px] uppercase tracking-wider t-muted font-semibold">{label}</dt>
      <dd className={`text-sm mt-0.5 truncate ${empty ? 't-muted' : 't-ink'} ${mono ? 'font-mono' : ''}`}>
        {empty ? '—' : value}
      </dd>
    </div>
  );
}

function YesNoRow({ label, value }) {
  if (value === undefined || value === null) {
    return (
      <div className="flex items-center justify-between gap-3 py-1.5">
        <span className="text-sm t-soft">{label}</span>
        <span className="text-xs t-muted">—</span>
      </div>
    );
  }
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <span className="text-sm t-soft">{label}</span>
      {value
        ? <span className="pill-amber">Yes</span>
        : <span className="pill-ink">No</span>}
    </div>
  );
}

function FindingRow({ label, value, tone }) {
  return (
    <div className="flex items-center justify-between text-sm py-1">
      <span className="t-soft">{label}</span>
      <span className={`text-xs px-2 py-0.5 rounded-md font-semibold border ${TONE[tone] || TONE.muted}`}>
        {value}
      </span>
    </div>
  );
}

function DecisionRadio({ checked, onChange, title, subtitle, tone }) {
  const accent = {
    good: 'border-emerald-500 bg-emerald-50',
    warn: 'border-amber-500 bg-amber-50',
    bad: 'border-red-500 bg-red-50',
  }[tone] || '';
  return (
    <label
      className={`flex items-start gap-3 p-3 rounded-md border cursor-pointer ${
        checked ? accent : 'border-[color:var(--border-cool)] hover:border-[color:var(--border-strong)]'
      }`}
    >
      <span
        className={`mt-0.5 w-5 h-5 rounded-full border-2 grid place-items-center shrink-0`}
        style={{ borderColor: checked ? 'var(--brand)' : 'var(--border-strong)' }}
      >
        {checked && <span className="w-2.5 h-2.5 rounded-full" style={{ background: 'var(--brand)' }} />}
      </span>
      <input type="radio" checked={checked} onChange={onChange} className="sr-only" />
      <div>
        <div className="text-sm font-semibold t-ink">{title}</div>
        <div className="text-xs t-muted mt-0.5">{subtitle}</div>
      </div>
    </label>
  );
}

const yn = (b) => (b ? 'Yes' : null);
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

const DISEASE_LABELS = {
  leprosy: 'Leprosy',
  lymphatic_filariasis: 'Lymphatic Filariasis',
  tuberculosis: 'Tuberculosis',
  scabies: 'Scabies',
  japanese_encephalitis: 'Japanese Encephalitis',
  malaria: 'Malaria',
  sickle_cell: 'Sickle Cell Disease',
};

// The 11-question leprosy symptom checklist (matches the agent screening form).
const LEPROSY_SYMPTOMS = [
  ['Light-coloured or reddish skin patch(es)', 'skin_patches'],
  ['Reduced or loss of sensation over skin patch(es)', 'patch_loss_of_sensation'],
  ['Tingling, numbness, or burning sensation in hands/feet', 'numb_tingling_burning'],
  ['Weakness in hands or feet', 'weakness_in_hands_or_feet'],
  ['Weak grip or objects slipping from hands', 'weak_grip'],
  ['Painless wounds, burns, or ulcers on hands/feet', 'painless_wounds'],
  ['Pain or tenderness near elbow, wrist, knee, or ankle', 'nerve_tenderness'],
  ['Foot slipping out of slippers/chappals or dragging while walking', 'foot_drop'],
  ['Difficulty closing eyes completely or reduced blinking', 'eye_closure_difficulty'],
  ['Loss of eyebrows, collapsed nose', 'eyebrow_loss_nasal_collapse'],
  ['Lumps/nodules on skin or swelling of earlobes', 'nodules_or_earlobe_swelling'],
];

const SYMPTOM_LABELS = {
  skin_patches: 'Light/reddish skin patches',
  patch_loss_of_sensation: 'Loss of sensation over patches',
  numb_tingling_burning: 'Tingling/numbness/burning hands/feet',
  weakness_in_hands_or_feet: 'Weakness in hands or feet',
  weak_grip: 'Weak grip / objects slipping',
  painless_wounds: 'Painless wounds/burns/ulcers',
  nerve_tenderness: 'Pain/tenderness near joints',
  foot_drop: 'Foot drop / dragging',
  eye_closure_difficulty: 'Difficulty closing eyes',
  eyebrow_loss_nasal_collapse: 'Eyebrow loss / collapsed nose',
  nodules_or_earlobe_swelling: 'Nodules / earlobe swelling',
};
const prettySymptom = (k) => SYMPTOM_LABELS[k] || k.replace(/_/g, ' ');

const RELATION_LABELS = {
  self: 'Self',
  father_mother: 'Father / Mother',
  husband_wife: 'Brother / Sister',
  brother_sister: 'Brother / Sister',
  son_daughter: 'Son / Daughter',
  grand_son_grand_daughter: 'Grand Son / Grand Daughter',
  others: 'Others',
};
const prettyRelation = (k) => (k ? RELATION_LABELS[k] || k : null);
const fmtDateTime = (iso) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('en-IN', {
      timeZone: 'Asia/Kolkata',
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return String(iso);
  }
};

// Screen-records the consultation (the Zoom window opens externally) and
// uploads the recording to the patient's Storage folder.
function ConsultRecorder({ caseId, onRecorded }) {
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);

  const start = async () => {
    setMsg(null);
    if (!navigator.mediaDevices?.getDisplayMedia) {
      setMsg('Screen recording is not supported in this browser.');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
      chunksRef.current = [];
      const mr = new MediaRecorder(stream, { mimeType: 'video/webm' });
      mr.ondataavailable = (e) => { if (e.data?.size) chunksRef.current.push(e.data); };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: 'video/webm' });
        setRecording(false);
        setBusy(true);
        try {
          await uploadFile(`/cases/${caseId}/recording`, blob, 'recording.webm');
          setMsg('Recording saved to the patient folder.');
          onRecorded?.();
        } catch (e) {
          setMsg(`Upload failed: ${e.message}`);
        } finally {
          setBusy(false);
        }
      };
      // If the user ends sharing via the browser bar, stop + upload.
      stream.getVideoTracks()[0]?.addEventListener('ended', () => {
        if (mr.state !== 'inactive') mr.stop();
      });
      mr.start();
      recorderRef.current = mr;
      setRecording(true);
    } catch (e) {
      setMsg(e.name === 'NotAllowedError' ? 'Screen share was cancelled.' : `Could not start recording: ${e.message}`);
    }
  };

  const stop = () => {
    if (recorderRef.current && recorderRef.current.state !== 'inactive') recorderRef.current.stop();
  };

  return (
    <div className="border-t border-[color:var(--border-cool)] pt-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="section-title !mb-1">Screen recording</div>
          <p className="text-[11px] t-muted">Records the consultation and stores it in the patient folder.</p>
        </div>
        {!recording ? (
          <button type="button" className="btn-ghost" onClick={start} disabled={busy}>
            {busy ? 'Uploading…' : (
              <span className="inline-flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-red-600" /> Start recording
              </span>
            )}
          </button>
        ) : (
          <button type="button" className="btn-danger" onClick={stop}>
            <span className="inline-flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-sm bg-white animate-pulse" /> Stop & save
            </span>
          </button>
        )}
      </div>
      {recording && <p className="text-xs text-red-600 font-medium mt-2">● Recording in progress…</p>}
      {msg && <p className="text-xs t-soft mt-2">{msg}</p>}
    </div>
  );
}

function TeleConsultBlock({
  caseId, onRecorded, appointment, when, setWhen, duration, setDuration, schedule, schedBusy, schedError,
}) {
  const phaseInfo = appointment
    ? meetingPhase(appointment.scheduled_at, appointment.duration_minutes || 30)
    : null;
  const isActive = phaseInfo?.phase === 'active';
  const isExpired = phaseInfo?.phase === 'expired';
  const isUpcoming = phaseInfo?.phase === 'upcoming';
  const hostUrl = appointment?.zoom_start_url || appointment?.zoom_join_url;
  const canStart = isActive && hostUrl;

  const SchedulerForm = ({ title, subtitle }) => (
    <div>
      <div className="section-title">Scheduler</div>
      <h3 className="text-lg font-semibold t-ink">{title}</h3>
      <p className="text-xs t-muted mb-3 mt-1">{subtitle}</p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div>
          <label className="label">When</label>
          <input type="datetime-local" className="neu-input" value={when} onChange={(e) => setWhen(e.target.value)} />
        </div>
        <div>
          <label className="label">Duration (min)</label>
          <input type="number" className="neu-input" value={duration} min={10} max={60} onChange={(e) => setDuration(+e.target.value)} />
        </div>
        <div className="flex items-end">
          <button className="btn-primary w-full" onClick={schedule} disabled={schedBusy}>
            {schedBusy ? '…' : 'Book Zoom consult'}
          </button>
        </div>
      </div>
      {schedError && <p className="text-sm text-red-600 mt-2">{schedError}</p>}
    </div>
  );

  // No appointment yet - show scheduler with a calm brand-bordered card so it draws the eye
  if (!appointment) {
    return (
      <section className="card-brand p-6">
        <SchedulerForm
          title="Schedule tele-consult"
          subtitle="Books a Zoom slot. Patient receives the join link via WhatsApp/SMS."
        />
      </section>
    );
  }

  return (
    <section className="card-brand p-6 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="section-title">Tele-consult</div>
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-lg font-semibold t-ink">Session</h3>
            {isExpired && <span className="pill-red">expired</span>}
            {isActive && <span className="pill-amber">live now</span>}
            {isUpcoming && <span className="pill-brand">scheduled</span>}
          </div>
          <div className="text-xs t-muted mt-1">
            <strong className="t-ink">{fmtDateTime(appointment.scheduled_at)}</strong> · {appointment.duration_minutes} min
            {phaseInfo?.label && (
              <span className={`ml-2 ${isExpired ? 'text-red-600 font-semibold' : isActive ? 't-ink font-semibold' : ''}`}>
                · {phaseInfo.label}
              </span>
            )}
          </div>
        </div>
        {!isExpired && (
          <a
            className={`btn-primary inline-flex items-center gap-2 ${!canStart ? 'opacity-50 pointer-events-none' : ''}`}
            href={canStart ? hostUrl : undefined}
            target="_blank"
            rel="noopener noreferrer"
            aria-disabled={!canStart}
            title={!canStart ? 'Available 5 minutes before the scheduled time' : undefined}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="23 7 16 12 23 17 23 7" /><rect x="1" y="5" width="15" height="14" rx="2" /></svg>
            {isActive ? 'Start Zoom consult' : 'Start (at slot time)'}
          </a>
        )}
      </div>

      {!isExpired && (appointment.zoom_meeting_id || appointment.zoom_join_url) && (
        <div>
          <MeetingDetails
            meetingId={appointment.zoom_meeting_id}
            password={appointment.zoom_password}
            joinUrl={appointment.zoom_join_url}
          />
          <p className="text-[10px] t-muted mt-1.5">
            Patient receives the same details via WhatsApp. Ask them to copy the passcode and paste it into Zoom if prompted.
          </p>
        </div>
      )}

      {!isExpired && <ConsultRecorder caseId={caseId} onRecorded={onRecorded} />}

      {isExpired && (
        <Banner kind="error">
          <div className="font-semibold">Session expired</div>
          <p className="text-xs t-soft mt-0.5">
            The scheduled slot has passed and the Zoom link is no longer active. Book a new session below if needed.
          </p>
        </Banner>
      )}

      {isExpired && (
        <div className="border-t border-[color:var(--border-cool)] pt-4">
          <SchedulerForm
            title="Schedule a new session"
            subtitle="Pick a fresh date and time. A new Zoom meeting will be created."
          />
        </div>
      )}
    </section>
  );
}