import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { IframeWithLoader } from "@/components/IframeWithLoader";

export const metadata = {
  title: "Tele-Lepra — Lepra Stack",
};

export default async function TelemedicinePage() {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }

  return (
    <IframeWithLoader
      src="/telemedicine-app"
      title="Tele-Lepra"
      allow="camera; microphone; fullscreen; display-capture; clipboard-write"
      loadingLabel="Loading Tele-Lepra…"
    />
  );
}
