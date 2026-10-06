// Tele-Lepra is served under a sub-path (/telemedicine-app/) when embedded
// in the Lepra Stack portal. A root-absolute string like "/logos/lepra.png"
// resolves against the *domain* root, not this app's base path, and since
// the portal has no generic rewrite for bare static paths, that request
// hits the portal's own public folder instead (404, or a same-named but
// unrelated file). Route every public-asset reference through this helper
// so it always resolves relative to Tele-Lepra's actual base path.
export function assetUrl(path) {
  const base = import.meta.env.BASE_URL.replace(/\/+$/, '');
  return `${base}/${String(path).replace(/^\/+/, '')}`;
}
