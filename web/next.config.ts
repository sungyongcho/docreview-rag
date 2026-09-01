import type { NextConfig } from "next";

const basePath = "/docreview-rag-agent";

const nextConfig: NextConfig = {
  agentRules: false,
  allowedDevOrigins: ["127.0.0.1"],
  basePath,
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
