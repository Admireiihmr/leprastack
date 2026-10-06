const partnerLogoClass = "h-5 sm:h-6 w-auto object-contain rounded-sm";

function PartnerLogos({ className = "" }: { className?: string }) {
  return (
    <div className={`flex items-center gap-3 sm:gap-4 ${className}`}>
      <a
        href="https://leprasociety.in/"
        target="_blank"
        rel="noopener noreferrer"
        className="rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
      >
        <img src="/lepra-logo.png" alt="LEPRA Society" className={partnerLogoClass} />
      </a>
      <a
        href="https://iihmrbangalore.edu.in/"
        target="_blank"
        rel="noopener noreferrer"
        className="rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
      >
        <img src="/iihmr-logo.png" alt="IIHMR Bangalore" className={partnerLogoClass} />
      </a>
      <img src="/kind-care-logo.jpeg" alt="Kind Care" className={partnerLogoClass} />
    </div>
  );
}

export function Footer() {
  return (
    <footer className="w-full border-t border-black/5 bg-white">
      <div className="px-4 py-4 text-center text-xs leading-relaxed text-black/50 sm:flex sm:flex-wrap sm:items-center sm:justify-between sm:gap-x-6 sm:px-6 sm:py-3 sm:text-left lg:px-10">
        {/* Mobile: condensed to the essentials, no redundant taglines */}
        <div className="flex flex-col items-center gap-2.5 sm:hidden">
          <p>&copy; Lepra Stack</p>
          <PartnerLogos />
        </div>

        {/* Tablet/desktop: full detail, unchanged */}
        <p className="hidden sm:block">
          &copy; Lepra Stack <span className="text-black/20">&middot;</span> Unified leprosy care
          platform <span className="text-black/20">&middot;</span> For authorised health workers
          only
        </p>

        <div className="hidden sm:flex sm:items-center sm:gap-3">
          <span className="text-[11px] uppercase tracking-wide text-black/35">In partnership with</span>
          <PartnerLogos />
        </div>
      </div>
    </footer>
  );
}
