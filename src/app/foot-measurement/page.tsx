import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { IframeWithLoader } from "@/components/IframeWithLoader";

export const metadata = {
  title: "DIMPLE AI Footwear Measurement — Lepra Stack",
};

export default async function FootMeasurementPage() {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }

  return (
    <IframeWithLoader
      src="/dimple-app"
      title="DIMPLE AI Footwear Measurement"
      allow="camera; microphone; fullscreen"
      loadingLabel="Loading DIMPLE AI Footwear Measurement…"
    />
  );
}
