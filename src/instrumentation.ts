export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const dns = await import("node:dns");
    // Some environments fail to route IPv6 to Neon's endpoint, causing
    // connect timeouts on the neon-http driver's fetch calls. Prefer IPv4.
    dns.setDefaultResultOrder("ipv4first");
  }
}
