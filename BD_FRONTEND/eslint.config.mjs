// ESLint flat configuration for the Alphaleo BD frontend.
// Needed so `npm run lint` (and later `make check`) enforces the Next.js and TypeScript rules.
// Uses the rule sets shipped by eslint-config-next; no custom rules are added in B1.
// B2 only adds the generated client folder to the ignore list; B4 adds the Playwright output folders.
import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Build output and generated files are not linted (the OpenAPI client is machine-written, B2).
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts", "src/lib/api/**", "test-results/**", "playwright-report/**"]),
]);

export default eslintConfig;
