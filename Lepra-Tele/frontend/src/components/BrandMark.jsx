export default function BrandMark({ size = 32, className = '' }) {
  return (
    <span
      className={`brand-mark ${className}`}
      style={{ width: size, height: size, borderRadius: size * 0.28 }}
      aria-hidden="true"
    >
      <svg
        viewBox="0 0 24 24"
        width={size * 0.62}
        height={size * 0.62}
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {/* medical cross + pulse line */}
        <path d="M12 4v6" />
        <path d="M9 7h6" />
        <path d="M3 17h3l2-4 3 8 2-6 2 2h6" />
      </svg>
    </span>
  );
}

export function BrandWordmark({ subtitle = 'Triage Console' }) {
  return (
    <div className="flex items-center gap-2.5">
      <BrandMark />
      <div className="leading-tight">
        <div className="font-bold tracking-wide text-ink-900 text-[15px]">
          TELE<span className="text-brand-700">-</span>LEPROSY
        </div>
        {subtitle && (
          <div className="text-[10px] uppercase tracking-[0.18em] text-ink-500">{subtitle}</div>
        )}
      </div>
    </div>
  );
}
