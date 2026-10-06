import { useState } from 'react';

/** Capture device GPS on demand. Calls onCapture({lat,lng,accuracy,altitude,captured_at})
 *  with an ISO-8601 captured_at. Stays silent if the browser/user blocks geolocation;
 *  shows the error inline.
 */
export default function GeoCaptureButton({ value, onCapture, label = 'Capture GPS' }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const capture = () => {
    setError(null);
    if (!navigator.geolocation) {
      setError('Geolocation is not available on this device.');
      return;
    }
    setBusy(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        onCapture({
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          accuracy: pos.coords.accuracy,
          altitude: pos.coords.altitude,
          captured_at: new Date(pos.timestamp).toISOString(),
        });
        setBusy(false);
      },
      (err) => {
        setError(err.message || 'Unable to capture location.');
        setBusy(false);
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
    );
  };

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={capture}
          disabled={busy}
          className="btn-ghost inline-flex items-center gap-1.5"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
            <circle cx="12" cy="10" r="3" />
          </svg>
          {busy ? 'Locating…' : value ? 'Recapture GPS' : label}
        </button>
        {value && (
          <span className="text-[11px] font-mono t-soft neu-inset px-2 py-1 rounded">
            {value.lat.toFixed(5)}, {value.lng.toFixed(5)}
            {value.accuracy != null && (
              <span className="t-muted"> · ±{Math.round(value.accuracy)}m</span>
            )}
          </span>
        )}
      </div>
      {error && (
        <p className="text-[11px] text-red-600 mt-1.5">{error}</p>
      )}
    </div>
  );
}
