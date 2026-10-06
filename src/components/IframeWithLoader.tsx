"use client";

import { useEffect, useState } from "react";
import { Spinner } from "@/components/Spinner";

const LOAD_TIMEOUT_MS = 25_000;

export function IframeWithLoader({
  src,
  title,
  allow,
  loadingLabel,
}: {
  src: string;
  title: string;
  allow?: string;
  loadingLabel: string;
}) {
  const [loaded, setLoaded] = useState(false);
  const [timedOut, setTimedOut] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setTimedOut(false);
    const timer = setTimeout(() => setTimedOut(true), LOAD_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [attempt]);

  const showError = timedOut && !loaded;

  return (
    <div className="relative flex-1 w-full">
      <div
        className={`absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-white transition-opacity duration-200 ease-out ${
          loaded ? "opacity-0 pointer-events-none" : "opacity-100"
        }`}
      >
        {showError ? (
          <>
            <p className="text-sm font-medium text-black/80">Taking longer than expected</p>
            <p className="max-w-xs text-center text-sm text-black/50">
              This can happen on a slow connection or if the service is starting up.
            </p>
            <button
              type="button"
              onClick={() => {
                setLoaded(false);
                setAttempt((a) => a + 1);
              }}
              className="mt-1 rounded-lg border border-black/10 px-4 py-2 text-sm font-medium text-black/80 hover:bg-black/5 transition-colors duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
            >
              Try again
            </button>
          </>
        ) : (
          <>
            <Spinner className="h-8 w-8 text-teal-600" />
            <p className="text-sm text-black/50">{loadingLabel}</p>
          </>
        )}
      </div>
      <iframe
        key={attempt}
        src={src}
        title={title}
        allow={allow}
        onLoad={() => setLoaded(true)}
        className="absolute inset-0 h-full w-full border-0"
      />
    </div>
  );
}
