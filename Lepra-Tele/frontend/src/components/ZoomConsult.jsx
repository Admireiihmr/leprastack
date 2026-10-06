import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { useAuth } from '../context/AuthContext';

/**
 * Embedded Zoom Meeting SDK consult.
 *
 * Backend mints a short-lived signature so the SDK secret never leaves the
 * server. If Zoom creds are not configured the join button degrades to
 * opening Zoom in a new tab via the saved join_url.
 */
export default function ZoomConsult({ appointmentId }) {
  const { user, profile } = useAuth();
  const [error, setError] = useState(null);
  const [info, setInfo] = useState(null);
  const containerRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api(`/appointments/${appointmentId}/zoom-signature`);
        if (cancelled) return;
        setInfo(data);

        const sdkKey = import.meta.env.VITE_ZOOM_SDK_KEY;
        if (!sdkKey || data.signature.startsWith('dev-signature')) {
          // Dev fallback: no real SDK, just show join button to external Zoom.
          return;
        }

        const { ZoomMtg } = await import('@zoom/meetingsdk');
        ZoomMtg.setZoomJSLib('https://source.zoom.us/3.11.2/lib', '/av');
        ZoomMtg.preLoadWasm();
        ZoomMtg.prepareWebSDK();

        ZoomMtg.init({
          leaveUrl: window.location.href,
          success: () => {
            ZoomMtg.join({
              signature: data.signature,
              sdkKey,
              meetingNumber: data.meeting_number,
              userName: profile?.profile?.name || user.email || 'Participant',
              userEmail: user.email || '',
              passWord: '',
              success: () => {},
              error: (e) => setError(JSON.stringify(e)),
            });
          },
          error: (e) => setError(JSON.stringify(e)),
        });
      } catch (e) {
        setError(String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [appointmentId, user, profile]);

  if (error) return <p className="text-sm text-red-600">Zoom error: {error}</p>;
  if (!info) return <p className="text-sm text-slate-500">Preparing meeting…</p>;

  const isDev = info.signature.startsWith('dev-signature');
  if (isDev) {
    return (
      <div className="space-y-2 text-sm">
        <p className="text-amber-700 bg-amber-50 border border-amber-200 p-2 rounded">
          Zoom SDK credentials not configured. Falling back to external join.
        </p>
        <a href={info.join_url} target="_blank" rel="noreferrer" className="btn-primary inline-block">
          Open Zoom (meeting {info.meeting_number})
        </a>
      </div>
    );
  }

  return (
    <div>
      <p className="text-xs text-slate-500 mb-2">Meeting {info.meeting_number}</p>
      <div ref={containerRef} id="zmmtg-root" />
    </div>
  );
}
