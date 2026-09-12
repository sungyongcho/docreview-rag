import { resolve } from "node:path";
import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants.js";

const basePath = "/docreview-rag";
const localHost = process.env.DOCREVIEW_LOCAL_HOST ?? "127.0.0.1";

export default function nextConfig(phase: string): NextConfig {
  const developmentServer = phase === PHASE_DEVELOPMENT_SERVER;
  const upstream = process.env.DOCREVIEW_API_UPSTREAM ?? "http://127.0.0.1:8000";
  return {
    agentRules: false,
    // Canonical retrieval JSON is shared with the API outside the web directory.
    turbopack: { root: resolve(process.cwd(), "..") },
    allowedDevOrigins: [...new Set([localHost, "localhost", "127.0.0.1"])],
    basePath,
    ...(developmentServer
      ? {
          experimental: { proxyTimeout: 660_000 },
          rewrites: async () => [
            {
              source: `${basePath}/api/:path*`,
              destination: `${upstream}/:path*`,
              basePath: false,
            },
          ],
        }
      : { output: "export" }),
    trailingSlash: true,
    images: { unoptimized: true },
  };
}
