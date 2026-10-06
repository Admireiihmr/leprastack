import Link from "next/link";
import { auth } from "@/lib/auth";
import { Navbar } from "@/components/Navbar";
import { Reveal, RevealGroup, RevealItem } from "@/components/motion/Reveal";
import { ArrowRightIcon, ShieldIcon, UsersIcon, HeartIcon, LockIcon } from "@/components/icons";

const modules = [
  {
    name: "DIMPLE AI Footwear Measurement",
    description:
      "AI-assisted leprosy foot measurement that helps clinicians fit protective footwear precisely and track deformity progression over time.",
    href: "/foot-measurement",
    badge: "bg-teal-600 text-white",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" className="h-6 w-6" strokeWidth={1.75}>
        <path
          d="M9 21c-1.5 0-2.5-1-2.5-2.5 0-1 .3-1.6.3-2.6 0-1.8-2-2.6-2-5.4C4.8 6.9 7 4 10 4c1.7 0 2.3 1 3.3 1s1.4-.6 2.4-.6c2 0 3.3 2 3.3 4.3 0 3-2.2 4.4-2.2 7 0 1.7.7 2.8.7 3.8 0 1.4-1.1 2.5-2.5 2.5-1.7 0-2-1-3-1s-1.3 1-3 1Z"
          stroke="currentColor"
        />
      </svg>
    ),
  },
  {
    name: "Tele-Lepra",
    description:
      "Secure video tele-consultation for leprosy case management, connecting field health workers with specialists for faster diagnosis.",
    href: "/telemedicine",
    badge: "bg-sky-600 text-white",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" className="h-6 w-6" strokeWidth={1.75}>
        <path
          d="M4 6a2 2 0 0 1 2-2h3l1.5 4-2 1.5a11 11 0 0 0 5 5l1.5-2 4 1.5v3a2 2 0 0 1-2 2C9.7 20 4 14.3 4 7Z"
          stroke="currentColor"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },

  {
    name: "Livelihood Support",
    description:
      "Welfare scheme enrolment and reimbursement tracking for people affected by leprosy, with field-agent and approver workflows.",
    href: "/livelihood",
    badge: "bg-amber-600 text-white",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" className="h-6 w-6" strokeWidth={1.75}>
        <path
          d="M3 9.5 12 4l9 5.5M5 11v7a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-7M9.5 19v-4.5h5V19"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
];

const steps = [
  {
    step: "01",
    title: "Register",
    description: "Health workers and clinicians sign up for secure access to the LepraStack platform.",
  },
  {
    step: "02",
    title: "Consult or Measure",
    description: "Run an AI-assisted foot measurement or start a tele-consultation with a specialist in minutes.",
  },
  {
    step: "03",
    title: "Track & Follow Up",
    description: "Case history, measurements, and consultation notes stay together for ongoing patient care.",
  },
];

const values = [
  { icon: ShieldIcon, title: "Secure by design", description: "Access is restricted to authorised health workers, with encrypted sessions throughout." },
  { icon: UsersIcon, title: "Built for the field", description: "Designed with frontline health workers so it holds up in real clinics, not just demos." },
  { icon: HeartIcon, title: "Patient centred", description: "Every tool exists to get patients diagnosed sooner and cared for better." },
];

const stats = [
  { value: "3", label: "Integrated care tools" },
  { value: "AI", label: "Assisted diagnostics" },
  { value: "24/7", label: "Secure platform access" },
  { value: "1", label: "Unified patient journey" },
];

export default async function Home() {
  const session = await auth();
  const isAuthenticated = Boolean(session?.user);
  const displayName = session?.user?.name ?? session?.user?.email ?? "";
  const firstName = displayName.split(" ")[0];
  const initial = displayName.charAt(0).toUpperCase();

  return (
    <>
      <Navbar
        isAuthenticated={isAuthenticated}
        user={isAuthenticated ? { firstName, initial } : null}
      />

      <main className="flex-1">
        {/* Hero */}
        <section className="relative overflow-hidden min-h-[520px] sm:min-h-[600px] flex flex-col items-center justify-center bg-[url('/hero-bg.jpg')] bg-cover bg-[30%_65%]">
          <div className="absolute inset-0 bg-white/40" />
          <div className="absolute inset-x-0 bottom-0 h-40 bg-gradient-to-b from-transparent to-white" />

          <div className="relative mx-auto max-w-4xl px-4 sm:px-6 py-20 sm:py-28 text-center">
            <Reveal>
              <span className="inline-flex items-center gap-2 rounded-full border border-teal-200 bg-teal-50 px-3.5 py-1.5 text-xs font-medium text-teal-800">
                {isAuthenticated ? "Welcome back" : "Unified leprosy care platform"}
              </span>
            </Reveal>

            <Reveal delay={0.08}>
              <h1 className="mt-6 text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight text-black">
                {isAuthenticated ? (
                  <>
                    Welcome back,{" "}
                    <span className="text-teal-700">
                      {firstName}
                    </span>
                  </>
                ) : (
                  <>
                    Better leprosy care,{" "}
                    <span className="text-teal-700">
                      one platform
                    </span>
                  </>
                )}
              </h1>
            </Reveal>

            <Reveal delay={0.16}>
              <p className="mt-5 text-base sm:text-lg text-black/60 max-w-2xl mx-auto leading-relaxed">
                {isAuthenticated
                  ? "Choose a tool below to continue, right here on Lepra Stack."
                  : "LepraStack brings AI-assisted foot measurement and tele-consultation together, so health workers can screen, consult, and track patients from a single, secure hub."}
              </p>
            </Reveal>

            <Reveal delay={0.24}>
              <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
                {isAuthenticated ? (
                  <a
                    href="#modules"
                    className="group inline-flex items-center gap-2 rounded-full bg-teal-600 hover:bg-teal-700 text-white text-base font-medium px-6 py-3.5 shadow-lg shadow-teal-900/15 transition-all duration-200 ease-out active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
                  >
                    Choose a tool
                    <ArrowRightIcon className="h-4 w-4 transition-transform duration-200 ease-out group-hover:translate-x-0.5" />
                  </a>
                ) : (
                  <>
                    <Link
                      href="/signup"
                      className="group inline-flex items-center gap-2 rounded-full bg-teal-600 hover:bg-teal-700 text-white text-base font-medium px-6 py-3.5 shadow-lg shadow-teal-900/15 transition-all duration-200 ease-out active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
                    >
                      Get started
                      <ArrowRightIcon className="h-4 w-4 transition-transform duration-200 ease-out group-hover:translate-x-0.5" />
                    </Link>
                    <a
                      href="#modules"
                      className="inline-flex items-center gap-2 rounded-full border border-black/10 bg-white hover:bg-black/5 text-black/80 text-base font-medium px-6 py-3.5 transition-colors duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
                    >
                      Explore the modules
                    </a>
                  </>
                )}
              </div>
            </Reveal>
          </div>

          {!isAuthenticated && (
            <RevealGroup className="relative mx-auto max-w-5xl px-4 sm:px-6 pb-16 sm:pb-20 grid grid-cols-2 sm:grid-cols-4 gap-4 sm:gap-6">
              {stats.map((stat) => (
                <RevealItem
                  key={stat.label}
                  className="rounded-2xl border border-black/5 bg-white/70 backdrop-blur-sm px-4 py-5 text-center shadow-sm"
                >
                  <div className="text-2xl sm:text-3xl font-bold text-teal-700">{stat.value}</div>
                  <div className="mt-1 text-xs sm:text-sm text-black/55">{stat.label}</div>
                </RevealItem>
              ))}
            </RevealGroup>
          )}
        </section>

        {/* Modules */}
        <section id="modules" className="mx-auto max-w-6xl px-4 sm:px-6 py-20 sm:py-28">
          <Reveal className="max-w-2xl mx-auto text-center">
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-black">
              {isAuthenticated ? "Your tools" : "Our modules"}
            </h2>
            <p className="mt-3 text-black/60">
              {isAuthenticated
                ? "Choose a tool below to continue, right here on Lepra Stack."
                : "Three purpose-built tools, one consistent experience. Sign in once to reach any of them."}
            </p>
          </Reveal>

          <RevealGroup className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {modules.map((mod) => (
              <RevealItem key={mod.href} className="h-full">
                <Link
                  href={isAuthenticated ? mod.href : "/login"}
                  target={isAuthenticated ? "_blank" : undefined}
                  rel={isAuthenticated ? "noopener noreferrer" : undefined}
                  className="group relative flex h-full flex-col overflow-hidden rounded-2xl border border-black/10 bg-white p-7 sm:p-8 shadow-sm hover:shadow-lg hover:-translate-y-0.5 hover:border-teal-300 transition-all duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
                >
                  <div className="relative inline-flex h-12 w-12 shrink-0">
                    <div className={`flex h-12 w-12 items-center justify-center rounded-xl shadow-sm ${mod.badge}`}>
                      {mod.icon}
                    </div>
                    {!isAuthenticated && (
                      <span className="absolute -right-1.5 -bottom-1.5 flex h-6 w-6 items-center justify-center rounded-full border-2 border-white bg-black/70 text-white">
                        <LockIcon className="h-3 w-3" />
                      </span>
                    )}
                  </div>
                  <h3 className="font-semibold text-lg text-black mt-5 group-hover:text-teal-700 transition-colors duration-200 ease-out">
                    {mod.name}
                  </h3>
                  <p className="text-sm text-black/60 mt-2 leading-relaxed">{mod.description}</p>
                  <span className="mt-auto pt-6 inline-flex items-center gap-1.5 text-sm font-medium text-teal-700">
                    {isAuthenticated ? "Open application" : "Sign in to access"}
                    {isAuthenticated ? (
                      <ArrowRightIcon className="h-4 w-4 transition-transform duration-200 ease-out group-hover:translate-x-0.5" />
                    ) : (
                      <LockIcon className="h-3.5 w-3.5" />
                    )}
                  </span>
                </Link>
              </RevealItem>
            ))}
          </RevealGroup>
        </section>

        {/* How it works */}
        <section id="how-it-works" className="bg-gradient-to-b from-white via-teal-50/40 to-white py-20 sm:py-28">
          <div className="mx-auto max-w-6xl px-4 sm:px-6">
            <Reveal className="max-w-2xl mx-auto text-center">
              <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-black">How it works</h2>
              <p className="mt-3 text-black/60">From sign-up to follow-up, in three steps.</p>
            </Reveal>

            <RevealGroup className="mt-12 grid gap-6 sm:grid-cols-3">
              {steps.map((s) => (
                <RevealItem
                  key={s.step}
                  className="rounded-2xl border border-black/10 bg-white p-7 shadow-sm"
                >
                  <span className="text-sm font-bold text-teal-600">{s.step}</span>
                  <h3 className="font-semibold text-black mt-3">{s.title}</h3>
                  <p className="text-sm text-black/60 mt-2 leading-relaxed">{s.description}</p>
                </RevealItem>
              ))}
            </RevealGroup>
          </div>
        </section>

        {/* About / values */}
        <section id="about" className="mx-auto max-w-6xl px-4 sm:px-6 py-20 sm:py-28">
          <Reveal className="max-w-2xl mx-auto text-center">
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-black">Why LepraStack</h2>
            <p className="mt-3 text-black/60">
              Built with health workers and clinicians, for the realities of leprosy care.
            </p>
          </Reveal>

          <RevealGroup className="mt-12 grid gap-6 sm:grid-cols-3">
            {values.map((v) => (
              <RevealItem key={v.title} className="text-center px-4">
                <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-teal-600 shadow-sm shadow-teal-900/20">
                  <v.icon className="h-6 w-6 text-white" />
                </div>
                <h3 className="font-semibold text-black mt-4">{v.title}</h3>
                <p className="text-sm text-black/60 mt-2 leading-relaxed">{v.description}</p>
              </RevealItem>
            ))}
          </RevealGroup>
        </section>

        {/* Partners */}
        <section className="bg-gradient-to-b from-white via-sky-50/30 to-white py-20 sm:py-28">
          <div className="mx-auto max-w-6xl px-4 sm:px-6">
            <Reveal className="max-w-2xl mx-auto text-center">
              <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-black">Trusted partners</h2>
              <p className="mt-3 text-black/60">
                Built and run in collaboration with organisations dedicated to leprosy care.
              </p>
            </Reveal>

            <RevealGroup className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3 max-w-5xl mx-auto">
              <RevealItem className="rounded-2xl border border-black/10 bg-white p-6 shadow-sm overflow-hidden">
                <a
                  href="https://leprasociety.in/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex items-center gap-4 rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
                >
                  <img
                    src="/lepra-logo.png"
                    alt="LEPRA Society"
                    className="h-16 w-24 shrink-0 rounded-lg object-contain"
                  />
                  <div className="min-w-0 flex-1">
                    <h3 className="font-semibold text-black group-hover:text-teal-700 transition-colors duration-200 ease-out">
                      LEPRA Society
                    </h3>
                    <p className="text-sm text-black/60 mt-0.5">Field partner supporting leprosy screening and patient care.</p>
                  </div>
                </a>
              </RevealItem>

              <RevealItem className="rounded-2xl border border-black/10 bg-white p-6 shadow-sm overflow-hidden">
                <a
                  href="https://iihmrbangalore.edu.in/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex items-center gap-4 rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
                >
                  <img
                    src="/iihmr-logo.png"
                    alt="IIHMR Bangalore"
                    className="h-16 w-24 shrink-0 rounded-lg object-contain"
                  />
                  <div className="min-w-0 flex-1">
                    <h3 className="font-semibold text-black group-hover:text-teal-700 transition-colors duration-200 ease-out">
                      IIHMR Bangalore
                    </h3>
                    <p className="text-sm text-black/60 mt-0.5">
                      Academic and research partner behind LepraStack&apos;s development.
                    </p>
                  </div>
                </a>
              </RevealItem>

              <RevealItem className="flex items-center gap-4 rounded-2xl border border-black/10 bg-white p-6 shadow-sm overflow-hidden">
                <img
                  src="/kind-care-logo.jpeg"
                  alt="Kind Care"
                  className="h-16 w-24 shrink-0 rounded-lg object-contain"
                />
                <div className="min-w-0 flex-1">
                  <h3 className="font-semibold text-black">Kind Care</h3>
                  <p className="text-sm text-black/60 mt-0.5">CSR wing of Mankind Pharma supporting patient outreach.</p>
                </div>
              </RevealItem>
            </RevealGroup>
          </div>
        </section>

        {/* Final CTA */}
        {!isAuthenticated && (
          <section className="mx-auto max-w-4xl px-4 sm:px-6 py-20 sm:py-28 text-center">
            <Reveal>
              <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-black">
                Ready to bring your team onto LepraStack?
              </h2>
              <p className="mt-3 text-black/60 max-w-xl mx-auto">
                Create an account to reach both tools from a single, secure sign-in.
              </p>
              <div className="mt-8">
                <Link
                  href="/signup"
                  className="group inline-flex items-center gap-2 rounded-full bg-teal-600 hover:bg-teal-700 text-white text-base font-medium px-6 py-3.5 shadow-lg shadow-teal-900/15 transition-all duration-200 ease-out active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
                >
                  Get started for free
                  <ArrowRightIcon className="h-4 w-4 transition-transform duration-200 ease-out group-hover:translate-x-0.5" />
                </Link>
              </div>
            </Reveal>
          </section>
        )}
      </main>
    </>
  );
}
