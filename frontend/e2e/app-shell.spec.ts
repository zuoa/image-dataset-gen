import { expect, test, type Page, type TestInfo } from "@playwright/test";

async function mockAppShellApi(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/v1/auth/refresh") {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          token: "e2e-token",
          user: { id: "e2e-user", username: "reviewer", plan: "pro" },
        }),
      });
      return;
    }
    if (pathname === "/api/v1/datasets") {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          datasets: [],
          summary: {
            totalDatasets: 0,
            activeDatasets: 0,
            totalTasks: 0,
            totalImages: 0,
            selectedImages: 0,
            costToDate: 0,
          },
        }),
      });
      return;
    }
    await route.abort();
  });
}

test("application shell uses persistent desktop navigation and an on-demand mobile drawer", async ({ page }, testInfo: TestInfo) => {
  await mockAppShellApi(page);
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/");

  await expect(page.getByText("Dataset Forge", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "新建数据集" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "数据集管理" })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("app-shell-desktop.png"), fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByText("Dataset Forge", { exact: true })).toBeHidden();
  await expect(page.getByRole("button", { name: "展开导航" })).toBeVisible();
  await page.getByRole("button", { name: "展开导航" }).click();
  const navigationDrawer = page.getByRole("dialog", { name: "主导航" });
  await expect(navigationDrawer.getByText("Dataset Forge", { exact: true })).toBeVisible();
  await expect(navigationDrawer.getByRole("button", { name: "新建数据集" })).toBeVisible();
  await expect(navigationDrawer.getByRole("button", { name: "关闭导航" })).toBeVisible();
  await page.waitForTimeout(350);
  await page.screenshot({ path: testInfo.outputPath("app-shell-mobile.png"), fullPage: true });
});
