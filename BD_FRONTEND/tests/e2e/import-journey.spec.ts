/**
 * The import demo journey in a real browser (task M2-A7, integration step I4).
 *
 * Needed as the one end-to-end proof that W1 (upload, mapping, preview, progress, report) and
 * W2 (quarantine release, duplicate merge) work together against the real API, the real worker
 * and the real ingest_row. It uploads a small synthetic CSV, imports it, reads the report,
 * fixes and releases a quarantined row, then merges a flagged duplicate.
 *
 * It needs the full stack (database, API and the WORKER, which runs the import job) and an
 * existing admin test account (E2E_ADMIN_*): an admin may import, assign and review duplicates.
 * Every run builds unique names and emails, because re-uploading identical bytes is refused as a
 * duplicate file (D-109) and earlier runs leave their leads behind.
 */
import { expect, test } from "@playwright/test";

import { readCredentials, submitLoginForm } from "./helpers";

// The import runs in the worker; allow time for it before giving up.
const IMPORT_TIMEOUT_MS = 90_000;

/** Builds the CSV: 6 data rows that each hit one real outcome (see the comments per row). */
function buildCsv(run: string): { filename: string; content: string } {
  const domain = `acme-${run}.example.com`;
  const last = `Lovelace${run}`;
  const rows = [
    ["First Name", "Last Name", "Email", "Title", "Contact Owner"],
    ["Ada", last, `ada@${domain}`, "Engineer", "Nobody Matches"], // new lead
    ["Alan", `Turing${run}`, `alan@${domain}`, "Analyst", ""], // new lead
    ["", `Hopper${run}`, `grace@${domain}`, "Admiral", ""], // no first name: quarantined
    ["Pat", `Personal${run}`, `pat-${run}@gmail.com`, "Tester", ""], // personal email: quarantined
    ["Ada", last, `ada@${domain}`, "Senior Engineer", ""], // same email: updates lead 1
    ["Ada", last, `ada.l@${domain}`, "Engineer", ""], // same name and domain: possible duplicate
  ];
  return {
    filename: `e2e-${run}.csv`,
    content: rows.map((row) => row.join(",")).join("\n") + "\n",
  };
}

test.describe("import journey", () => {
  test("admin: upload, map, import, report, release a quarantined row, merge a duplicate", async ({
    page,
  }) => {
    test.setTimeout(IMPORT_TIMEOUT_MS * 2);
    const run = Date.now().toString(36);
    const { filename, content } = buildCsv(run);

    await submitLoginForm(page, readCredentials("admin"));
    await expect(page).toHaveURL(/\/leads/);

    // 1. Upload. The file moves to the import's own URL, which hosts the wizard.
    await page.goto("/leads/import");
    await page.getByLabel("CSV or XLSX file").setInputFiles({
      name: filename,
      mimeType: "text/csv",
      buffer: Buffer.from(content),
    });
    await page.getByRole("button", { name: "Upload" }).click();
    await expect(page).toHaveURL(/\/leads\/import\/[0-9a-f-]{36}$/);

    // 2. Profile step: no profile, no default country.
    await page.getByRole("button", { name: "Continue" }).click();

    // 3. Mapping: the Apollo header names are suggested automatically; save them, then go on.
    await expect(page.getByRole("heading", { name: "Map the columns" })).toBeVisible();
    await page.getByRole("button", { name: "Save mapping" }).click();
    await page.getByRole("button", { name: "Continue" }).click();

    // 4. Preview and start.
    await expect(page.getByRole("heading", { name: "Preview and estimate" })).toBeVisible();
    await page.getByRole("button", { name: "Start import" }).click();

    // 5. Progress until the worker finishes, then the report.
    await expect(page.getByRole("heading", { name: "Import progress" })).toBeVisible();
    await page.getByRole("link", { name: "View the full report" }).click({
      timeout: IMPORT_TIMEOUT_MS,
    });
    await expect(page.getByRole("heading", { name: "Import report", level: 2 })).toBeVisible();
    const reportUrl = page.url();
    // The updated lead's title change is listed in the change summary.
    await expect(page.getByText("Senior Engineer")).toBeVisible();

    // 6. Quarantine: fix the row that had no first name, then release it (real ingest_row).
    await page.goto("/leads/quarantine");
    const rowLabel = `row 4 of ${filename}`;
    await page.getByRole("button", { name: `Edit ${rowLabel}` }).click();
    await page.getByLabel("First name").fill("Grace");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText(/ready to release/i).first()).toBeVisible();
    await page.getByRole("button", { name: `Release ${rowLabel}` }).click();
    await expect(page.getByRole("button", { name: `Release ${rowLabel}` })).toHaveCount(0);

    // 7. Duplicates: the second "Ada" was flagged; keep the first record and merge them.
    await page.goto("/leads/duplicates");
    await page
      .getByRole("button", { name: new RegExp(`^Review Ada Lovelace${run}`) })
      .first()
      .click();
    await page.getByRole("button", { name: "Merge", exact: true }).click();
    await page.getByRole("button", { name: "Confirm merge" }).click();
    await expect(page.getByText("Merged. The two records are now one lead.")).toBeVisible();

    // 8. The report is still readable afterwards.
    await page.goto(reportUrl);
    await expect(page.getByRole("heading", { name: "Import report", level: 2 })).toBeVisible();
  });
});
