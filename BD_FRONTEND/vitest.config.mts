// Vitest configuration for the component tests (task B4).
// Needed so `npm test` renders React components in a fake browser (jsdom), resolves the same
// "@/..." imports as the app, and runs only tests/unit (tests/e2e belongs to Playwright).
// Named .mts so Node loads it as an ES module (the package itself is CommonJS).
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()], // compiles JSX/TSX the same way as the app
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["tests/unit/**/*.test.{ts,tsx}"],
    // Fallback so a test that imports the real api-client does not throw on the missing URL;
    // component tests fake the client and never make a request.
    env: { NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000" },
  },
});
