/**
 * Next.js build configuration for the Alphaleo BD frontend.
 *
 * Needed so the production build is self-contained; the Dockerfile copies
 * `.next/standalone`, which only exists when `output: "standalone"` is set.
 */
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
};

export default nextConfig;
