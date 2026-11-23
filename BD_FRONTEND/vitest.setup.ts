// Vitest setup file, run before every test file (task B4).
// Needed to add the DOM matchers (toBeInTheDocument, toBeDisabled, ...) and to unmount rendered
// components after each test so one test never sees another test's page.
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Vitest globals are off, so Testing Library cannot register its automatic cleanup itself.
afterEach(() => {
  cleanup();
});
