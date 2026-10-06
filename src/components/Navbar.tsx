"use client";

import { useState } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { Logo } from "@/components/Logo";
import { MenuIcon, CloseIcon, ArrowRightIcon } from "@/components/icons";
import { signOutAction } from "@/app/actions/auth";

const navLinks = [
  { href: "#modules", label: "Tools" },
  { href: "#how-it-works", label: "How it works" },
  { href: "#about", label: "About" },
];

export function Navbar({
  isAuthenticated,
  user,
}: {
  isAuthenticated: boolean;
  user?: { firstName: string; initial: string } | null;
}) {
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-30 w-full border-b border-black/5 bg-white/80 backdrop-blur-md">
      <div className="flex w-full items-center justify-between gap-3 px-4 sm:px-6 lg:px-10 xl:px-16 py-4">
        <Link href="/" onClick={() => setOpen(false)}>
          <Logo />
        </Link>

        <nav className="hidden md:flex items-center gap-8">
          {navLinks.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="text-sm font-medium text-black/65 hover:text-teal-700 transition-colors duration-200 ease-out rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
            >
              {link.label}
            </a>
          ))}
        </nav>

        <div className="hidden md:flex items-center gap-3">
          {isAuthenticated ? (
            <>
              <div className="flex items-center gap-2">
                <div className="h-8 w-8 shrink-0 rounded-full bg-teal-600 text-white text-sm font-medium flex items-center justify-center">
                  {user?.initial}
                </div>
                <span className="text-sm text-black/70">{user?.firstName}</span>
              </div>
              <form action={signOutAction}>
                <button
                  type="submit"
                  className="rounded-lg border border-black/10 px-3 py-1.5 text-sm font-medium text-black/80 hover:bg-black/5 transition-colors duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
                >
                  Log out
                </button>
              </form>
            </>
          ) : (
            <>
              <Link
                href="/login"
                className="text-sm font-medium text-black/70 hover:text-black transition-colors duration-200 ease-out px-3 py-2 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
              >
                Sign in
              </Link>
              <Link
                href="/signup"
                className="group inline-flex items-center gap-1.5 rounded-full bg-teal-600 hover:bg-teal-700 text-white text-sm font-medium px-4 py-2 shadow-sm shadow-teal-900/15 transition-all duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
              >
                Get started
                <ArrowRightIcon className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
              </Link>
            </>
          )}
        </div>

        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-label={open ? "Close menu" : "Open menu"}
          className="md:hidden inline-flex h-9 w-9 items-center justify-center rounded-lg text-black/70 hover:bg-black/5 transition-colors duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
        >
          {open ? <CloseIcon className="h-5 w-5" /> : <MenuIcon className="h-5 w-5" />}
        </button>
      </div>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: "easeInOut" }}
            className="md:hidden overflow-hidden border-t border-black/5 bg-white"
          >
            <div className="flex flex-col gap-1 px-4 sm:px-6 py-4">
              {navLinks.map((link) => (
                <a
                  key={link.href}
                  href={link.href}
                  onClick={() => setOpen(false)}
                  className="rounded-lg px-3 py-2.5 text-sm font-medium text-black/70 hover:bg-black/5 transition-colors duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
                >
                  {link.label}
                </a>
              ))}
              <div className="mt-2 flex flex-col gap-2 border-t border-black/5 pt-3">
                {isAuthenticated ? (
                  <>
                    <div className="flex items-center gap-2 px-3 py-1.5">
                      <div className="h-8 w-8 shrink-0 rounded-full bg-teal-600 text-white text-sm font-medium flex items-center justify-center">
                        {user?.initial}
                      </div>
                      <span className="text-sm text-black/70">{user?.firstName}</span>
                    </div>
                    <form action={signOutAction}>
                      <button
                        type="submit"
                        className="w-full rounded-lg border border-black/10 px-3 py-2.5 text-sm font-medium text-black/80 hover:bg-black/5 text-left transition-colors duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
                      >
                        Log out
                      </button>
                    </form>
                  </>
                ) : (
                  <>
                    <Link
                      href="/login"
                      onClick={() => setOpen(false)}
                      className="rounded-lg px-3 py-2.5 text-sm font-medium text-black/70 hover:bg-black/5 transition-colors duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
                    >
                      Sign in
                    </Link>
                    <Link
                      href="/signup"
                      onClick={() => setOpen(false)}
                      className="inline-flex items-center justify-center gap-1.5 rounded-full bg-teal-600 hover:bg-teal-700 text-white text-sm font-medium px-4 py-2.5 transition-colors duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
                    >
                      Get started
                      <ArrowRightIcon className="h-3.5 w-3.5" />
                    </Link>
                  </>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}
