import { auth } from "@/lib/auth";
import { NextResponse } from "next/server";

const protectedPrefixes = ["/dashboard", "/telemedicine", "/foot-measurement", "/livelihood"];

export default auth((req) => {
  const isLoggedIn = !!req.auth?.user;
  const isProtected = protectedPrefixes.some((prefix) =>
    req.nextUrl.pathname.startsWith(prefix)
  );

  if (isProtected && !isLoggedIn) {
    const loginUrl = new URL("/login", req.nextUrl.origin);
    return NextResponse.redirect(loginUrl);
  }
});

export const config = {
  matcher: ["/dashboard/:path*", "/telemedicine/:path*", "/foot-measurement/:path*", "/livelihood/:path*"],
};
