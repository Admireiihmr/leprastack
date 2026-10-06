import { useEffect, useState } from 'react';
import { api } from '../../../lib/api';

export default function ScheduleStep({ caseId, onDone }) {
  const [mos, setMos] = useState([]);
  const [moUid, setMoUid] = useState('');
  const [when, setWhen] = useState('');
  const [duration, setDuration] = useState(20);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api('/admin/mos')
      .then((list) => {
        setMos(list);
        if (list[0]) setMoUid(list[0].uid);
      })
      .catch(() => setMos([]));
    // default to 1 hour from now
    const d = new Date(Date.now() + 60 * 60 * 1000);
    d.setSeconds(0, 0);
    setWhen(d.toISOString().slice(0, 16));
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api('/appointments', {
        method: 'POST',
        body: JSON.stringify({
          case_id: caseId,
          mo_uid: moUid,
          scheduled_at: new Date(when).toISOString(),
          duration_minutes: duration,
        }),
      });
      onDone();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="card-elev">
      <header className="mb-5">
        <h2 className="text-lg font-semibold t-ink">Schedule MO consult</h2>
        <p className="text-sm t-muted mt-1">
          Books a Zoom slot. Patient gets a join link via WhatsApp (stub).
        </p>
      </header>

      <section>
        <div className="section-title mb-3">Consult Details</div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="md:col-span-2">
            <label className="block text-xs font-medium t-soft mb-1.5">Medical Officer</label>
            <select className="neu-input" value={moUid} onChange={(e) => setMoUid(e.target.value)}>
              {mos.length === 0 && <option value="">(no MOs configured)</option>}
              {mos.map((m) => (
                <option key={m.uid} value={m.uid}>
                  {m.name || m.email}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium t-soft mb-1.5">When</label>
            <input
              type="datetime-local"
              className="neu-input"
              value={when}
              onChange={(e) => setWhen(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="block text-xs font-medium t-soft mb-1.5">Duration (min)</label>
            <input
              type="number"
              className="neu-input"
              value={duration}
              min={10}
              max={60}
              onChange={(e) => setDuration(+e.target.value)}
            />
          </div>
        </div>
      </section>

      {error && (
        <div className="text-sm text-red-700 border border-red-200 bg-red-50 rounded-md px-3 py-2 mt-4">
          {error}
        </div>
      )}

      <div className="flex justify-end mt-6">
        <button className="btn-primary" disabled={busy || !moUid}>
          {busy ? '…' : 'Book appointment'}
        </button>
      </div>
    </form>
  );
}
