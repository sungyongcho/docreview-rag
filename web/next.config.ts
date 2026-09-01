import type { NextConfig } from "next";

const basePath = "/docreview-rag-agent";
const localHost = process.env.DOCREVIEW_LOCAL_HOST ?? "127.0.0.1";

const nextConfig: NextConfig = {
  agentRules: false,
  allowedDevOrigins: [localHost],
  basePath,
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
