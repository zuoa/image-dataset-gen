import { expect, test, type Page, type TestInfo } from "@playwright/test";

function collection(id: string, name: string, parentId: string | null, stats?: Partial<Record<string, number>>) {
  return {
    id,
    parentId,
    name,
    description: `${name} grouping`,
    path: parentId ? `/${parentId}/${id}/` : `/${id}/`,
    depth: parentId ? 2 : 1,
    position: 0,
    stats: {
      datasetCount: stats?.datasetCount ?? 1,
      imageCount: stats?.imageCount ?? 4,
      spentCost: 1.2,
      directDatasetCount: stats?.directDatasetCount ?? 0,
      childCollectionCount: stats?.childCollectionCount ?? 1,
    },
  };
}

async function mockCollectionTree(page: Page) {
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
          datasets: [
            {
              id: "helmet",
              name: "安全帽",
              description: "劳动防护安全帽样本",
              categories: ["helmet", "no_helmet"],
              status: "ready",
              imageCount: 4,
              selectedCount: 4,
              taskCount: 1,
              spentCost: 1.2,
              annotation: {},
              collectionId: "ppe",
              collectionPath: [
                { id: "safety", name: "安全生产" },
                { id: "ppe", name: "人员劳动防护" },
              ],
              images: [],
              imagesTotal: 4,
              tasks: [],
              exports: [],
            },
          ],
          collections: [
            collection("safety", "安全生产", null, { childCollectionCount: 1, datasetCount: 1 }),
            collection("ppe", "人员劳动防护", "safety", { childCollectionCount: 0, directDatasetCount: 1, datasetCount: 1 }),
          ],
          summary: {
            totalDatasets: 1,
            activeDatasets: 0,
            totalTasks: 1,
            totalImages: 4,
            selectedImages: 4,
            costToDate: 1.2,
            totalCollections: 2,
          },
        }),
      });
      return;
    }
    await route.abort();
  });
}

test("dataset list drills into nested collections and returns via breadcrumb", async ({ page }, testInfo: TestInfo) => {
  await mockCollectionTree(page);
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "数据集管理" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "安全生产" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "安全帽" })).toHaveCount(0);

  await page.getByRole("heading", { name: "安全生产" }).click();
  await expect(page).toHaveURL(/collection=safety/);
  await expect(page.getByRole("heading", { name: "人员劳动防护" })).toBeVisible();

  await page.getByRole("heading", { name: "人员劳动防护" }).click();
  await expect(page).toHaveURL(/collection=ppe/);
  await expect(page.getByRole("heading", { name: "安全帽" })).toBeVisible();

  await page.getByRole("link", { name: "全部数据集" }).click();
  await expect(page).toHaveURL(/\/(\?.*)?$/);
  await expect(page.getByRole("heading", { name: "安全生产" })).toBeVisible();

  await page.getByPlaceholder("按名称、描述、类别或路径过滤").fill("安全帽");
  await expect(page.getByRole("heading", { name: "安全帽" })).toBeVisible();
  await expect(page.getByText("安全生产 / 人员劳动防护", { exact: true })).toBeVisible();

  await page.screenshot({ path: testInfo.outputPath("dataset-collections-desktop.png"), fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?collection=ppe");
  await expect(page.getByRole("heading", { name: "安全帽" })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("dataset-collections-mobile.png"), fullPage: true });
});
