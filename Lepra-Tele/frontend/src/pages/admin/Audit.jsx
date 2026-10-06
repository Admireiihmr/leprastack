import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import { formatId } from '../../lib/ids';

export default function Audit() {
  const [sample, setSample] = useState([]);
  const [pct, setPct] = useState(5);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    return api(`/admin/audit-sample?pct=${pct}`).then(setSample).finally(() => setLoading(false));
  };
  useEffect(() => {
    load();
  }, []);

  return (
    <div>
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4 mb-6">
        <div>
          <div className="section-title">Quality control</div>
          <h1 className="text-2xl font-semibold tracking-tight t-ink">Audit sample</h1>
          <p className="text-sm t-muted mt-1 max-w-2xl">
            Random sample of rule-out cases for independent review. Used to track missed-case rate.
          </p>
        </div>
        <div>
          <span className="pill-brand">{sample.length} sampled</span>
        </div>
      </div>

      <div className="space-y-5">
        <section className="card-elev">
          <div className="flex flex-wrap items-end gap-4">
            <div>
              <label className="block text-[11px] uppercase tracking-wider t-muted font-semibold mb-1.5">Sample %</label>
              <input
                type="number"
                className="input max-w-[120px]"
                value={pct}
                min={1}
                max={100}
                onChange={(e) => setPct(+e.target.value)}
              />
            </div>
            <button className="btn-ghost" onClick={load}>Resample</button>
            <div className="ml-auto text-xs t-muted">
              {loading ? 'Loading…' : `${sample.length} records`}
            </div>
          </div>
        </section>

        <section className="card-elev p-0 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-[11px] uppercase tracking-wider t-muted">
                <tr className="border-b border-[color:var(--border)]">
                  <th className="text-left font-semibold px-4 py-2.5">Timestamp</th>
                  <th className="text-left font-semibold px-4 py-2.5">Case ID</th>
                  <th className="text-left font-semibold px-4 py-2.5">Patient</th>
                  <th className="text-left font-semibold px-4 py-2.5">Outcome</th>
                  <th className="text-left font-semibold px-4 py-2.5">Reasons</th>
                </tr>
              </thead>
              <tbody>
                {loading && sample.length === 0 && (
                  [...Array(5)].map((_, i) => (
                    <tr key={i} className="border-b border-[color:var(--border)] last:border-0 animate-pulse">
                      <td className="px-4 py-3" colSpan={5}>
                        <div className="h-4 w-full max-w-md bg-[color:var(--surface-2)] rounded-md" />
                      </td>
                    </tr>
                  ))
                )}
                {sample.map((c) => (
                  <tr
                    key={c.id}
                    className="border-b border-[color:var(--border)] last:border-0 hover:bg-[color:var(--surface-2)] align-top"
                  >
                    <td className="px-4 py-3 font-mono text-xs t-muted whitespace-nowrap">
                      {new Date(c.created_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs t-soft">{formatId(c.id)}</td>
                    <td className="px-4 py-3 t-ink">{c.patient_name}</td>
                    <td className="px-4 py-3"><span className="pill-green">rule out</span></td>
                    <td className="px-4 py-3 t-soft">
                      {c.triage?.reasons && c.triage.reasons.length > 0 ? (
                        <ul className="space-y-0.5">
                          {c.triage.reasons.slice(0, 3).map((r, i) => (
                            <li key={i} className="text-xs">{r}</li>
                          ))}
                        </ul>
                      ) : (
                        <span className="text-xs t-muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
                {sample.length === 0 && !loading && (
                  <tr>
                    <td colSpan={5} className="px-4 py-10 text-center text-sm t-muted">
                      No rule-out cases to audit yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}
