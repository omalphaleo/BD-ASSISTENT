/**
 * Configuration for @hey-api/openapi-ts, the generator of the typed API client (task B2).
 *
 * Needed so the frontend never hand-writes API code (CLAUDE.md): `npm run generate:api` turns the
 * committed `BD_BACKEND/openapi.json` into `src/lib/api/`. Both the login page (B3) and the
 * CSRF handling (B12) build on the generated functions; the runtime setup lives in
 * `src/lib/api-client.ts`, outside the generated folder.
 */
import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  // Read-only contract owned by Developer A; B never edits it.
  input: "../BD_BACKEND/openapi.json",
  output: "src/lib/api",
  plugins: ["@hey-api/typescript", "@hey-api/sdk", "@hey-api/client-fetch"],
});
