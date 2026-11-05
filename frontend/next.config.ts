import type { NextConfig } from "next";

// The tunnel teachers' phones use during UAT (29 October), e.g.
// https://elimu-uat.ngrok-free.app. The development server refuses its own
// scripts to any other host unless the host is listed here.
const publicHost = (() => {
  try {
    return process.env.PUBLIC_URL ? new URL(process.env.PUBLIC_URL).host : null;
  } catch {
    return null;
  }
})();

const config: NextConfig = {
  allowedDevOrigins: publicHost ? [publicHost] : [],
  // The FastAPI backend is a separate service. Proxying /api through Next in
  // development means the browser sees one origin, so the refresh cookie is
  // first-party and SameSite never has to be weakened to make it work.
  async rewrites() {
    const api = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};

export default config;
