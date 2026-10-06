/**
 * Resolve a file in public/ against the app's base path.
 *
 * A root-absolute "/lepra-logo.png" only works when this app owns the origin.
 * Under the Lepra Stack portal it is served from /livelihood-app/, where that
 * path resolves to the portal instead and 404s, so prefix with BASE_URL —
 * which Vite sets to "/" standalone and "/livelihood-app/" when embedded.
 */
export function assetUrl(path: string): string {
  return `${import.meta.env.BASE_URL}${path.replace(/^\/+/, "")}`;
}
