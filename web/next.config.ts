import { resolve } from "node:path";
import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants.js";
import { buildMetadata } from "./scripts/build-metadata.mjs";

const basePath = "/docreview-rag";
const localHost = process.env.DOCREVIEW_LOCAL_HOST ?? "127.0.0.1";
const build = buildMetadata();

export default function nextConfig(phase: string): NextConfig {
  const developmentServer = phase === PHASE_DEVELOPMENT_SERVER;
  const upstream = process.env.DOCREVIEW_API_UPSTREAM ?? "http://127.0.0.1:8000";
  return {
    agentRules: false,
    ...(process.env.DOCREVIEW_SCREENSHOT_MODE === "1" ? { devIndicators: false as const } : {}),
    // Canonical retrieval JSON is shared with the API outside the web directory.
    turbopack: { root: resolve(process.cwd(), "..") },
    allowedDevOrigins: [...new Set([localHost, "localhost", "127.0.0.1"])],
    basePath,
    env: {
      NEXT_PUBLIC_DOCREVIEW_BUILD_FINGERPRINT: build.fingerprint,
      NEXT_PUBLIC_DOCREVIEW_BUILT_AT: build.builtAt,
    },
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
