"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { signupSchema, type SignupInput } from "@/lib/validation";
import { signupAction } from "@/app/actions/auth";
import { AuthPageShell } from "@/components/auth/AuthPageShell";
import { AuthField } from "@/components/auth/AuthField";
import { MailIcon, LockIcon, UserIcon, EyeIcon, EyeOffIcon, ArrowRightIcon } from "@/components/icons";
import { Spinner } from "@/components/Spinner";

export default function SignupPage() {
  const router = useRouter();
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting, isSubmitSuccessful },
  } = useForm<SignupInput>({
    resolver: zodResolver(signupSchema),
    defaultValues: { name: "", email: "", password: "", confirmPassword: "" },
  });

  const onSubmit = async (data: SignupInput) => {
    setSubmitError(null);
    try {
      const result = await signupAction(data);

      if (!result.success) {
        for (const [field, message] of Object.entries(result.errors)) {
          if (field === "form") {
            setSubmitError(message ?? "Something went wrong. Please try again.");
          } else {
            setError(field as keyof SignupInput, { message });
          }
        }
        return;
      }

      router.push("/login?registered=1");
    } catch {
      setSubmitError("Something went wrong. Please try again.");
    }
  };

  return (
    <AuthPageShell>
      <h1 className="text-2xl font-bold text-black">Create an account</h1>
      <p className="text-base text-black/60 mb-6 sm:mb-8">
        Sign up to access the Lepra Stack portal
      </p>

      <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
        <AuthField
          id="name"
          type="text"
          autoComplete="name"
          placeholder="Enter your name"
          ariaLabel="Name"
          icon={UserIcon}
          disabled={isSubmitting}
          error={errors.name?.message}
          registration={register("name")}
        />

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
          autoComplete="new-password"
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

        <AuthField
          id="confirmPassword"
          type={showConfirmPassword ? "text" : "password"}
          autoComplete="new-password"
          placeholder="Confirm your password"
          ariaLabel="Confirm password"
          icon={LockIcon}
          disabled={isSubmitting}
          error={errors.confirmPassword?.message}
          registration={register("confirmPassword")}
          rightSlot={
            <button
              type="button"
              onClick={() => setShowConfirmPassword((v) => !v)}
              aria-label={showConfirmPassword ? "Hide password" : "Show password"}
              className="absolute right-3.5 top-1/2 -translate-y-1/2 text-black/35 hover:text-black/60 transition-colors duration-200 ease-out rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
            >
              {showConfirmPassword ? <EyeOffIcon className="h-5 w-5" /> : <EyeIcon className="h-5 w-5" />}
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
          disabled={isSubmitting || isSubmitSuccessful}
          className="w-full inline-flex items-center justify-center gap-2 rounded-full bg-teal-600 hover:bg-teal-700 disabled:opacity-60 text-white text-base font-medium py-3.5 shadow-lg shadow-teal-900/15 transition-all duration-200 ease-out active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
        >
          {isSubmitting && <Spinner className="h-4 w-4" />}
          {isSubmitting ? "Creating account..." : "Sign up"}
          {!isSubmitting && <ArrowRightIcon className="h-4 w-4" />}
        </button>
      </form>

      <div className="flex items-center gap-3 my-6">
        <div className="h-px flex-1 bg-black/10" />
        <span className="text-xs text-black/40">or</span>
        <div className="h-px flex-1 bg-black/10" />
      </div>

      <p className="text-sm text-center text-black/60">
        Already have an account?{" "}
        <Link
          href="/login"
          className="text-teal-700 font-semibold hover:underline transition-colors duration-200 ease-out rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 focus-visible:ring-offset-2"
        >
          Log in
        </Link>
      </p>
    </AuthPageShell>
  );
}
