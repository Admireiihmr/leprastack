import { SproutIcon } from "@/components/icons";

export function Logo({
  className = "",
  iconOnly = false,
}: {
  className?: string;
  iconOnly?: boolean;
}) {
  return (
    <div className={`inline-flex items-center gap-2.5 ${className}`}>
      <span className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-teal-600 shadow-sm shadow-teal-900/20">
        <SproutIcon className="h-5 w-5 text-white" />
      </span>
      {!iconOnly && (
        <span className="text-xl font-bold tracking-tight text-teal-700">
          Lepra Stack
        </span>
      )}
    </div>
  );
}

export function AuthBrand({ tagline }: { tagline: string }) {
  return (
    <div className="flex flex-col items-center text-center">
      <span className="flex h-16 w-16 items-center justify-center rounded-full bg-teal-600 shadow-lg shadow-teal-900/20">
        <SproutIcon className="h-8 w-8 text-white" />
      </span>
      <h2 className="mt-3 text-2xl font-bold tracking-tight">
        <span className="text-teal-700">
          Lepra Stack
        </span>
      </h2>
      <p className="mt-1 text-sm text-black/60">{tagline}</p>
    </div>
  );
}
