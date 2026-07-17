import { test, expect } from "@playwright/test";

test.describe("auth page visual regression", () => {
  test("auth page renders consistently", async ({ page }) => {
    await page.goto("/auth");
    await page.waitForLoadState("networkidle");
    const heading = page.getByRole("heading", { name: "Dataset Forge" });
    await expect(heading).toBeVisible({ timeout: 30_000 });
    await expect(page).toHaveScreenshot("auth-page.png", {
      fullPage: true,
      animations: "disabled",
    });
  });
});
