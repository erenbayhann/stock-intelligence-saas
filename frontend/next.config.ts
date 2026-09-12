import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // "frontend" is this service's own hostname on the docker-compose network
  // (used when debugging tools run in another container reach it via that
  // network instead of the published localhost:3000 port). Without this,
  // Next's dev server blocks /_next/hmr and other dev-only resources for
  // that origin — which doesn't just break HMR, it silently prevents the
  // client bundle from ever hydrating, so every "use client" component's
  // effects (chart rendering, count-up animations, etc.) never run at all.
  // Dev-only setting — harmless in production (next start ignores it).
  allowedDevOrigins: ["frontend"],
  // Production Docker image only needs .next/standalone's self-contained
  // server.js + a copy of public/ and .next/static — not full node_modules.
  output: "standalone",
};

export default nextConfig;
