import { useEffect, useMemo, useState } from 'react';
import { api } from '../../lib/api';

const ROLES = ['agent', 'mo', 'admin'];

const ROLE_PILL = {
  patient: 'pill-ink',
  agent: 'pill-brand',
  mo: 'pill-amber',
  admin: 'pill-red',
};

export default function Users() {
  const [list, setList] = useState([]);
  const [msg, setMsg] = useState(null);
  const [query, setQuery] = useState('');

  const load = () => api('/admin/users').then(setList);
  useEffect(() => {
    load();
  }, []);

  const setRole = async (uid, role) => {
    setMsg(null);
    try {
      await api('/auth/set-role', {
        method: 'POST',
        body: JSON.stringify({ uid, role }),
      });
      setMsg(`Updated ${uid.slice(0, 6)} → ${role}`);
      load();
    } catch (e) {
      setMsg(`Error: ${e.message}`);
    }
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return list;
    return list.filter((u) =>
      (u.email || '').toLowerCase().includes(q) ||
      (u.name || '').toLowerCase().includes(q) ||
      (u.role || '').toLowerCase().includes(q),
    );
  }, [list, query]);

  return (
    <div>
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4 mb-6">
        <div>
          <div className="section-title">Access control</div>
          <h1 className="text-2xl font-semibold tracking-tight t-ink">Users</h1>
          <p className="text-sm t-muted mt-1">Assign roles to control access across the console.</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="pill-brand">{list.length} {list.length === 1 ? 'user' : 'users'}</span>
        </div>
      </div>

      <div className="space-y-5">
        {msg && (
          <div className="neu-inset rounded-md px-4 py-2.5 text-sm t-soft">{msg}</div>
        )}

        <section className="card-elev">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div className="flex-1 max-w-sm">
              <input
                type="text"
                className="input"
                placeholder="Search by name, email, or role"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <div className="text-xs t-muted">
              {filtered.length} of {list.length} shown
            </div>
          </div>
        </section>

        <section className="card-elev p-0 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-[11px] uppercase tracking-wider t-muted">
                <tr className="border-b border-[color:var(--border)]">
                  <th className="text-left font-semibold px-4 py-2.5">Email</th>
                  <th className="text-left font-semibold px-4 py-2.5">Name</th>
                  <th className="text-left font-semibold px-4 py-2.5">Role</th>
                  <th className="text-left font-semibold px-4 py-2.5">Change role</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((u) => (
                  <tr
                    key={u.uid}
                    className="border-b border-[color:var(--border)] last:border-0 hover:bg-[color:var(--surface-2)]"
                  >
                    <td className="px-4 py-3 t-ink font-mono text-xs">{u.email}</td>
                    <td className="px-4 py-3 t-soft">{u.name || '—'}</td>
                    <td className="px-4 py-3">
                      <span className={ROLE_PILL[u.role] || 'pill-ink'}>{u.role}</span>
                    </td>
                    <td className="px-4 py-3">
                      <select
                        className="input max-w-[160px]"
                        value={u.role}
                        onChange={(e) => setRole(u.uid, e.target.value)}
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>{r}</option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-4 py-10 text-center t-muted">No users found.</td>
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
