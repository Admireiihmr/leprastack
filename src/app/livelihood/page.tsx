import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { IframeWithLoader } from "@/components/IframeWithLoader";

export const metadata = {
  title: "Livelihood Support — Lepra Stack",
};

export default async function LivelihoodPage() {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }

  return (
    <IframeWithLoader
      src="/livelihood-app"
      title="Livelihood Support"
      allow="fullscreen; clipboard-write"
      loadingLabel="Loading Livelihood Support…"
    />
  );
}
