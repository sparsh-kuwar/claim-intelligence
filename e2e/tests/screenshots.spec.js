// Generates docs/screenshots/*.png. Run after `python backend/scripts/load_samples.py` on a fresh DB.
import { expect, test } from "@playwright/test";

const OUT = "../docs/screenshots";
const API = process.env.E2E_API_URL || "http://localhost:8000";

test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to regenerate docs/screenshots");
test.use({ viewport: { width: 1440, height: 900 } });

test("capture screenshots", async ({ page, request }) => {
  // put a couple of claims in final states so the dashboard shows the full lifecycle
  await request.post(`${API}/api/claims/CLM-10002/approve`, { data: { reviewer: "analyst" } });
  await request.post(`${API}/api/claims/CLM-10004/escalate`, { data: { reviewer: "analyst", reason: "Safety incident - route to product safety team" } });

  await page.goto("/");
  await expect(page.getByTestId("claims-table")).toContainText("CLM-10008");
  await page.screenshot({ path: `${OUT}/01-dashboard.png`, fullPage: true });

  await page.goto("/new");
  await page.getByRole("button", { name: "PDF example (low confidence)" }).click();
  await page.screenshot({ path: `${OUT}/02-intake-form.png`, fullPage: true });
  await page.getByRole("button", { name: "Submit claim" }).click();
  await expect(page.getByTestId("open-claim")).toBeVisible();
  await page.screenshot({ path: `${OUT}/03-intake-receipt.png`, fullPage: true });

  await page.goto("/claims/CLM-10001");
  await expect(page.getByTestId("ai-table")).toBeVisible();
  await page.screenshot({ path: `${OUT}/04-ai-analysis-needs-review.png`, fullPage: true });

  await page.getByTestId("approve").click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByTestId("decision-panel").screenshot({ path: `${OUT}/05-approval-blocked.png` });

  await page.getByTestId("accept-suspectedCause").click();
  await expect(page.getByTestId("row-suspectedCause")).toContainText("ACCEPTED");
  await page.getByTestId("accept-affectedPart").click();
  await expect(page.getByTestId("row-affectedPart")).toContainText("ACCEPTED");
  await page.getByTestId("edit-resolution").click();
  await page.getByTestId("row-resolution").locator("input").fill("Inspect/replace power module");
  await page.getByTestId("comment").fill("Technician evidence required.");
  await page.getByTestId("ai-table").screenshot({ path: `${OUT}/06-human-review-edit.png` });
  await page.getByTestId("save-resolution").click();
  await expect(page.getByTestId("row-resolution")).toContainText("EDITED");
  await page.getByTestId("approve").click();
  await expect(page.getByTestId("final-record")).toBeVisible();
  await page.screenshot({ path: `${OUT}/07-approved-validated-record.png`, fullPage: true });

  await page.goto("/claims/CLM-10005");
  await expect(page.getByTestId("rules")).toBeVisible();
  await page.screenshot({ path: `${OUT}/08-warranty-conflict-rules.png`, fullPage: true });

  await page.goto("/claims/CLM-10004");
  await expect(page.getByTestId("status-badge").first()).toHaveText("Escalated");
  await page.screenshot({ path: `${OUT}/09-escalated-critical.png`, fullPage: true });

  await page.goto("/review");
  await expect(page.getByTestId("claims-table")).toContainText("CLM-");
  await page.screenshot({ path: `${OUT}/10-review-queue.png`, fullPage: true });

  await page.goto(`${API}/docs`);
  await page.waitForSelector(".opblock", { timeout: 15000 }).catch(() => {});
  await page.screenshot({ path: `${OUT}/11-swagger-api-docs.png`, fullPage: true });
});
