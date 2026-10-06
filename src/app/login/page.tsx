"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { signIn } from "next-auth/react";
import { loginSchema, type LoginInput } from "@/lib/validation";
import { AuthPageShell } from "@/components/auth/AuthPageShell";
import { AuthField } from "@/components/auth/AuthField";
import { MailIcon, LockIcon, EyeIcon, EyeOffIcon, ArrowRightIcon, ShieldIcon, UsersIcon, HeartIcon } from "@/components/icons";
import { Spinner } from "@/components/Spinner";

function LoginFormContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const justRegistered = searchParams.get("registered") === "1";
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginInput>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  const onSubmit = async (data: LoginInput) => {
    setSubmitError(null);
    try {
      const result = await signIn("credentials", {
        ...data,
        redirect: false,
      });

      if (!result || result.error) {
        setSubmitError("Invalid email or password");
        return;
      }

      router.push("/");
      router.refresh();
    } catch {
      setSubmitError("Something went wrong. Please try again.");
    }
  };

  return (
    <>
      <h1 className="text-2xl font-bold text-black">Welcome back</h1>
      <p className="text-base text-black/60 mb-6 sm:mb-8">Sign in to continue to your account</p>

      {justRegistered && (
        <p className="mb-4 rounded-xl bg-green-50 text-green-700 text-sm px-3 py-2.5 border border-green-100">
          Account created. You can now log in.
        </p>
      )}

      <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
        <AuthField
          id="email"
          type="email"
          autoComplete="email"
          placeholder="Enter your email"
          ariaLabel="Email"
          icon={MailIcon}
          disabled={isSubmitting}
          error={errors.email?.message}
          registration={register("email")}
        />

        <AuthField
          id="password"
          type={showPassword ? "text" : "password"}
          autoComplete="current-password"
          placeholder="Enter your password"
          ariaLabel="Password"
          icon={LockIcon}
          disabled={isSubmitting}
          error={errors.password?.message}
          registration={register("password")}
          rightSlot={
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? "Hide password" : "Show password"}
              className="absolute right-3.5 top-1/2 -translate-y-1/2 text-black/35 hover:text-black/60 transition-colors duration-200 ease-out rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
            >
              {showPassword ? <EyeOffIcon className="h-5 w-5" /> : <EyeIcon className="h-5 w-5" />}
            </button>
          }
        />

        {submitError && (
          <p className="rounded-xl bg-red-50 border border-red-100 px-3 py-2.5 text-sm text-red-600">
            {submitError}
          </p>
        )}

        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full inline-flex items-center justify-center gap-2 rounded-full bg-teal-600 hover:bg-teal-700 disabled:opacity-60 text-white text-base font-medium py-3.5 shadow-lg shadow-teal-900/15 transition-all duration-200 ease-out active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
        >
          {isSubmitting && <Spinner className="h-4 w-4" />}
          {isSubmitting ? "Signing in..." : "Sign in"}
          {!isSubmitting && <ArrowRightIcon className="h-4 w-4" />}
        </button>
      </form>

      <div className="flex items-center gap-3 my-6">
        <div className="h-px flex-1 bg-black/10" />
        <span className="text-xs text-black/40">or</span>
        <div className="h-px flex-1 bg-black/10" />
      </div>

      <p className="text-sm text-center text-black/60">
        Don&apos;t have an account?{" "}
        <Link
          href="/signup"
          className="text-teal-700 font-semibold hover:underline transition-colors duration-200 ease-out rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
        >
          Sign up
        </Link>
      </p>
    </>
  );
}

const trustItems = [
  { icon: ShieldIcon, label: "Secure Access" },
  { icon: UsersIcon, label: "Patient Centric" },
  { icon: HeartIcon, label: "Better Together" },
];

function TrustBadges() {
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2 sm:gap-x-6 text-black/55">
      {trustItems.map((item, i) => (
        <div key={item.label} className="flex items-center gap-4 sm:gap-6">
          {i > 0 && <div className="h-4 w-px bg-black/15" />}
          <div className="flex items-center gap-1.5">
            <item.icon className="h-4 w-4 text-teal-600" />
            <span className="text-xs sm:text-sm">{item.label}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function LoginPage() {
  return (
    <AuthPageShell footer={<TrustBadges />}>
      <Suspense fallback={null}>
        <LoginFormContent />
      </Suspense>
    </AuthPageShell>
  );
}
