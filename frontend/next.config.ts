import { networkInterfaces } from "node:os";

import type { NextConfig } from "next";

// The development server refuses its own scripts to any host but localhost
// unless the host is listed in allowedDevOrigins - and it compares HOSTNAMES,
// without the port. Two kinds of host need listing:
//
//   - The tunnel teachers' phones used during UAT (29 October), e.g.
//     https://elimu-uat.ngrok-free.app, given as PUBLIC_URL.
//   - This laptop's own addresses on the local network (17 November), so a
//     phone on the same Wi-Fi can open http://<laptop address>:3000 with no
//     tunnel. Read from the network adapters at start-up, so a new address
//     from the router needs only a restart, not a setting.
//
// The first version passed `URL.host`, which keeps the port. That never
// mattered for the tunnel (https has no port in the address), but for a
// laptop address it is "192.168.1.20:3000", which never matches, and the
// page loaded without its scripts: the sign-in form submitted itself as a
// plain GET, with the password in the address bar.
const publicHost = (() => {
  try {
    return process.env.PUBLIC_URL ? new URL(process.env.PUBLIC_URL).hostname : null;
  } catch {
    return null;
  }
})();

/** Private IPv4 addresses of this machine (Wi-Fi, Ethernet, hotspot). */
function lanAddresses(): string[] {
  const out: string[] = [];
  for (const list of Object.values(networkInterfaces())) {
    for (const a of list ?? []) {
      if (a.family === "IPv4" && !a.internal && /^(10|192\.168|172\.(1[6-9]|2\d|3[01]))\./.test(a.address)) {
        out.push(a.address);
      }
    }
  }
  return out;
}

const config: NextConfig = {
  allowedDevOrigins: [...(publicHost ? [publicHost] : []), ...lanAddresses()],
  // The FastAPI backend is a separate service. Proxying /api through Next in
  // development means the browser sees one origin, so the refresh cookie is
  // first-party and SameSite never has to be weakened to make it work.
  async rewrites() {
    const api = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};

export default config;
