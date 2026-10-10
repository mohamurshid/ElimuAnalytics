import type { NextConfig } from "next";

const config: NextConfig = {
  // The FastAPI backend is a separate service. Proxying /api through Next in
  // development means the browser sees one origin, so the refresh cookie is
  // first-party and SameSite never has to be weakened to make it work.
  async rewrites() {
    const api = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};

export default config;
