"use client";

import { usePathname } from "next/navigation";
import { Footer } from "@/components/Footer";

const noFooterPrefixes = ["/telemedicine", "/foot-measurement", "/livelihood"];

export function ConditionalFooter() {
  const pathname = usePathname();
  if (noFooterPrefixes.some((prefix) => pathname.startsWith(prefix))) {
    return null;
  }
  return <Footer />;
}
