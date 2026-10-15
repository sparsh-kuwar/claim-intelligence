import { expect, test } from "@playwright/test";

async function submitSample(page, label) {
  await page.goto("/new");
  await page.getByRole("button", { name: label }).click();
  await page.getByRole("button", { name: "Submit claim" }).click();
  await expect(page.getByTestId("receipt-id")).toHaveText(/CLM-\d+/);
  const id = await page.getByTestId("receipt-id").innerText();
  await expect(page.getByTestId("open-claim")).toBeVisible();
  return id;
}

test("intake form validates required fields client-side", async ({ page }) => {
  await page.goto("/new");
  await page.getByRole("button", { name: "Submit claim" }).click();
  await expect(page.getByText("Customer name is required")).toBeVisible();
  await expect(page.getByText("Describe the issue (min 10 characters)")).toBeVisible();
  await expect(page.getByText("Select warranty status")).toBeVisible();
});

test("low-confidence claim: human review -> accept/edit -> approve -> export", async ({ page }) => {
  const id = await submitSample(page, "PDF example (low confidence)");
  await expect(page.getByTestId("receipt")).toContainText("Routed to human review");
  await page.getByTestId("open-claim").click();

  await expect(page.getByTestId("claim-title")).toHaveText(id);
  await expect(page.getByTestId("review-warning")).toContainText("not verified facts");
  await expect(page.getByTestId("row-suspectedCause")).toContainText("LOW CONFIDENCE");

  // Approve is blocked while flagged fields are undecided
  await page.getByTestId("approve").click();
  await expect(page.getByRole("alert")).toContainText("Review decision required");

  await page.getByTestId("accept-suspectedCause").click();
  await expect(page.getByTestId("row-suspectedCause")).toContainText("ACCEPTED");
  await page.getByTestId("accept-affectedPart").click();
  await expect(page.getByTestId("row-affectedPart")).toContainText("ACCEPTED");

  await page.getByTestId("edit-resolution").click();
  await page.getByTestId("row-resolution").locator("input").fill("Inspect/replace power module");
  await page.getByTestId("save-resolution").click();
  await expect(page.getByTestId("row-resolution")).toContainText("EDITED");

  await page.getByTestId("comment").fill("Technician evidence required.");
  await page.getByTestId("approve").click();

  await expect(page.getByTestId("status-badge").first()).toHaveText("Approved");
  const record = page.getByTestId("final-record");
  await expect(record).toContainText('"resolution": "Inspect/replace power module"');
  await expect(record).toContainText('"approvalPath": "HUMAN_REVIEW"');
  await expect(record).toContainText("Human edited");

  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("download-json").click()]);
  expect(download.suggestedFilename()).toBe(`${id}.json`);
  await expect(page.getByTestId("timeline")).toContainText("APPROVED");
});

test("clean claim is ready for approval and approves without edits", async ({ page }) => {
  await submitSample(page, "Clean claim");
  await expect(page.getByTestId("receipt")).toContainText("All validation rules passed");
  await page.getByTestId("open-claim").click();
  await expect(page.getByTestId("status-badge").first()).toHaveText("Ready for Approval");
  await page.getByTestId("approve").click();
  await expect(page.getByTestId("final-record")).toContainText('"approvalPath": "AUTO_ELIGIBLE"');
});

test("critical safety claim is escalated with a reason", async ({ page }) => {
  await submitSample(page, "Safety hazard");
  await page.getByTestId("open-claim").click();
  await expect(page.getByTestId("rules")).toContainText("CRITICAL severity requires human sign-off");
  await page.getByTestId("escalate").click();
  await expect(page.getByRole("alert")).toContainText("escalation reason");
  await page.getByTestId("comment").fill("Safety incident - route to product safety team");
  await page.getByTestId("escalate").click();
  await expect(page.getByTestId("status-badge").first()).toHaveText("Escalated");
});

test("review queue lists only claims needing review", async ({ page }) => {
  await page.goto("/review");
  await expect(page.getByRole("heading", { name: "Human Review Queue" })).toBeVisible();
  const badges = page.getByTestId("claims-table").getByTestId("status-badge");
  await expect(badges.first()).toBeVisible();
  for (const text of await badges.allInnerTexts()) expect(text).toBe("Needs Review");
});
