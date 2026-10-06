import type { NextConfig } from "next";

const DIMPLE_BACKEND = "http://127.0.0.1:7860";
const LIVELIHOOD_APP = "http://127.0.0.1:5175";
const TELEMEDICINE_APP = "http://127.0.0.1:5176";
const TELEMEDICINE_BACKEND = "http://127.0.0.1:7861";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["192.168.200.193"],
  // Next's built-in gzip compression buffers responses to build valid gzip
  // frames, which silently breaks real-time streaming (Server-Sent Events)
  // on proxied routes like /progress/:run_id — the DIMPLE app's live
  // inference-progress bar never updates because the browser (which always
  // sends Accept-Encoding: gzip) gets nothing until the stream closes.
  // Disabling compression here is the standard fix when nothing in front
  // (e.g. IIS) is already handling it; can revisit once IIS is fronting
  // this with its own compression.
  compress: false,
  experimental: {
    // Next silently caps request bodies passed through rewrites/proxying at
    // 10MB by default. The DIMPLE app's /predict upload (6 full-resolution
    // phone camera photos) routinely exceeds that, so Next truncates the
    // body before forwarding it to the FastAPI backend — the backend then
    // gets a corrupt/incomplete multipart payload and the connection drops
    // (surfaces as a 500 with no matching backend log entry, since the
    // request never actually arrived intact). Raised well above what six
    // photos should ever need.
    proxyClientMaxBodySize: "150mb",
  },
  async rewrites() {
    return [
      { source: "/dimple-app", destination: `${DIMPLE_BACKEND}/` },
      { source: "/dimple-app/", destination: `${DIMPLE_BACKEND}/` },
      { source: "/dimple-app/signup", destination: `${DIMPLE_BACKEND}/signup` },
      { source: "/livelihood-app", destination: `${LIVELIHOOD_APP}/livelihood-app/` },
      { source: "/livelihood-app/:path*", destination: `${LIVELIHOOD_APP}/livelihood-app/:path*` },
      { source: "/telemedicine-app", destination: `${TELEMEDICINE_APP}/telemedicine-app/` },
      { source: "/telemedicine-app/:path*", destination: `${TELEMEDICINE_APP}/telemedicine-app/:path*` },
      { source: "/telemedicine-api/:path*", destination: `${TELEMEDICINE_BACKEND}/:path*` },
      { source: "/api/login", destination: `${DIMPLE_BACKEND}/api/login` },
      { source: "/api/logout", destination: `${DIMPLE_BACKEND}/api/logout` },
      { source: "/api/change-password", destination: `${DIMPLE_BACKEND}/api/change-password` },
      { source: "/api/me", destination: `${DIMPLE_BACKEND}/api/me` },
      { source: "/api/agents", destination: `${DIMPLE_BACKEND}/api/agents` },
      { source: "/api/agents/:path*", destination: `${DIMPLE_BACKEND}/api/agents/:path*` },
      { source: "/api/centers", destination: `${DIMPLE_BACKEND}/api/centers` },
      { source: "/api/dashboard", destination: `${DIMPLE_BACKEND}/api/dashboard` },
      { source: "/api/dashboard/drilldown", destination: `${DIMPLE_BACKEND}/api/dashboard/drilldown` },
      { source: "/api/export/csv", destination: `${DIMPLE_BACKEND}/api/export/csv` },
      { source: "/api/runs/:path*", destination: `${DIMPLE_BACKEND}/api/runs/:path*` },
      { source: "/api/stats", destination: `${DIMPLE_BACKEND}/api/stats` },
      { source: "/api/signup", destination: `${DIMPLE_BACKEND}/api/signup` },
      { source: "/api/signup-options", destination: `${DIMPLE_BACKEND}/api/signup-options` },
      { source: "/api/validate-view", destination: `${DIMPLE_BACKEND}/api/validate-view` },
      { source: "/api/history", destination: `${DIMPLE_BACKEND}/api/history` },
      { source: "/health", destination: `${DIMPLE_BACKEND}/health` },
      { source: "/runs/:path*", destination: `${DIMPLE_BACKEND}/runs/:path*` },
      { source: "/progress/:path*", destination: `${DIMPLE_BACKEND}/progress/:path*` },
      { source: "/report/:path*", destination: `${DIMPLE_BACKEND}/report/:path*` },
      { source: "/result/:path*", destination: `${DIMPLE_BACKEND}/result/:path*` },
      { source: "/predict", destination: `${DIMPLE_BACKEND}/predict` },
      { source: "/samples/:path*", destination: `${DIMPLE_BACKEND}/samples/:path*` },
    ];
  },
};

export default nextConfig;
