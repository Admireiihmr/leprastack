import type { ReactNode } from "react";
import { AuthBrand } from "@/components/Logo";

export function AuthPageShell({
  children,
  footer,
}: {
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <main className="relative flex flex-1 items-center justify-center px-4 py-10 sm:py-12 overflow-hidden bg-[url('/login-bg.jpg')] bg-cover bg-center">
      <div className="absolute inset-0 bg-white/35" />
      <div className="relative z-10 w-full flex flex-col items-center gap-6 sm:gap-8">
        <AuthBrand tagline="Unified portal for the Lepra Stack applications" />

        <div className="w-full max-w-lg rounded-2xl border border-black/10 bg-white/95 p-6 sm:p-10 shadow-sm">
          {children}
        </div>

        {footer}
      </div>
    </main>
  );
}
