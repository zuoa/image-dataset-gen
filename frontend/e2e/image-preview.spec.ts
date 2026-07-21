import { expect, test, type Page, type TestInfo } from "@playwright/test";

const promptText = "道路上的配送车辆，样本 1";

function previewSvg(label: string) {
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" viewBox="0 0 1200 800">
      <defs>
        <linearGradient id="sky" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stop-color="#3f7799" />
          <stop offset="1" stop-color="#d8c9ad" />
        </linearGradient>
      </defs>
      <rect width="1200" height="800" fill="url(#sky)" />
      <rect y="540" width="1200" height="260" fill="#334155" />
      <rect x="190" y="350" width="760" height="240" rx="42" fill="#e2e8f0" />
      <rect x="650" y="270" width="230" height="190" rx="32" fill="#cbd5e1" />
      <rect x="690" y="305" width="140" height="95" rx="16" fill="#31536d" />
      <circle cx="360" cy="610" r="78" fill="#111827" />
      <circle cx="360" cy="610" r="35" fill="#94a3b8" />
      <circle cx="820" cy="610" r="78" fill="#111827" />
      <circle cx="820" cy="610" r="35" fill="#94a3b8" />
      <text x="52" y="82" fill="white" font-family="system-ui" font-size="34">${label}</text>
    </svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

function makeImages(count = 2) {
  return Array.from({ length: count }, (_, index) => index + 1).map((ordinal) => ({
    id: `image-${ordinal}`,
    datasetId: "demo",
    sourceType: "generation",
    sourceOrdinal: ordinal,
    ordinal,
    status: "completed",
    latencyMs: 420,
    seed: 1000 + ordinal,
    promptText: `道路上的配送车辆，样本 ${ordinal}`,
    diversityVars: {},
    previewSvg: previewSvg(`Sample ${ordinal}`),
    selected: true,
    annotationStatus: "annotated",
    confidenceScore: 0.92,
    source: "generation",
    split: "train",
    detections: [
      { category: "truck", confidence: 0.94, bbox: [0.49, 0.6, 0.64, 0.48] },
      { category: "wheel", confidence: 0.88, bbox: [0.3, 0.79, 0.14, 0.2] },
    ],
  }));
}

async function mockDatasetDetailApi(
  page: Page,
  exports: Array<Record<string, unknown>> = [],
  imageCount = 2,
) {
  const images = makeImages(imageCount);
  const dataset = {
    id: "demo",
    name: "城市道路车辆样本集",
    description: "用于配送车辆识别的演示数据集",
    categories: ["truck", "wheel", "person"],
    status: "ready",
    imageCount: images.length,
    selectedCount: images.length,
    taskCount: 0,
    spentCost: 1.24,
    annotation: {},
    images,
    imagesTotal: images.length,
    imagesNextCursor: null,
    imageAnnotationCounts: { annotated: images.length, unannotated: 0 },
    imageClassCounts: { truck: 2, wheel: 2, person: 0 },
    imageSplitCounts: { train: 2, val: 0, test: 0, unselected: 0 },
    imageSourceCounts: { generation: 2, imported: 0, augmentation: 0 },
    selectedOriginalCount: images.length,
    unretainedUnannotatedImageCount: 0,
    tasks: [],
    exports,
    latestTask: null,
  };

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (url.pathname === "/api/v1/auth/refresh") {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          token: "e2e-token",
          user: { id: "e2e-user", username: "reviewer", plan: "pro" },
        }),
      });
      return;
    }

    if (request.method() === "GET" && url.pathname === "/api/v1/datasets/demo") {
      const offset = Number(url.searchParams.get("images_offset") ?? 0);
      const limitValue = url.searchParams.get("images_limit");
      const pageImages = limitValue === null
        ? images
        : images.slice(offset, offset + Number(limitValue));
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ dataset: { ...dataset, images: pageImages } }),
      });
      return;
    }

    if (request.method() === "GET" && url.pathname.includes("/exports/") && url.pathname.endsWith("/download")) {
      await route.fulfill({ contentType: "application/zip", body: "mock zip archive" });
      return;
    }

    if (request.method() === "GET" && url.pathname === "/api/v1/datasets/demo/training-jobs") {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jobs: [] }) });
      return;
    }

    if (request.method() === "GET" && url.pathname === "/api/v1/datasets/demo/quality-runs") {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ qualityRuns: [] }) });
      return;
    }

    await route.abort();
  });
}

async function openPreview(page: Page) {
  await page.goto("/datasets/demo");
  const previewButton = page.getByRole("button", { name: "查看样本 #1 详情" });
  await expect(previewButton).toBeVisible();
  await previewButton.click();
  const dialog = page.getByRole("dialog").filter({
    has: page.getByRole("region", { name: "图片画布" }),
  });
  await expect(dialog).toBeVisible();
  return dialog;
}

test("dataset detail groups operations and uses structured sample filters", async ({
  page,
}, testInfo: TestInfo) => {
  await mockDatasetDetailApi(page);
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/datasets/demo");

  await expect(
    page.getByRole("heading", { name: "城市道路车辆样本集" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "生成样本" })).toBeVisible();
  await expect(page.getByRole("button", { name: "导入样本" })).toBeVisible();
  await expect(page.getByRole("button", { name: "处理数据" })).toBeVisible();
  await expect(page.getByRole("button", { name: "训练与导出" })).toBeVisible();
  await expect(page.getByLabel("按样本来源筛选")).toBeVisible();
  await expect(page.getByLabel("按标注状态筛选")).toBeVisible();
  await expect(page.getByRole("combobox", { name: "按类别筛选" })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "按数据划分筛选" })).toBeVisible();

  await page.getByRole("button", { name: "设置保留状态" }).click();
  await page.getByText("全部不保留", { exact: true }).click();
  const confirmDialog = page.locator(".ant-modal-confirm").filter({ hasText: "全部不保留" });
  const confirmButton = confirmDialog.locator(".ant-btn-primary");
  await expect(confirmDialog).toBeVisible();
  const confirmButtonBackground = await confirmButton.evaluate(
    (element) => window.getComputedStyle(element).backgroundColor,
  );
  const confirmButtonChannels = confirmButtonBackground.match(/\d+/g)?.map(Number) ?? [];
  expect(confirmButtonBackground).not.toBe("rgb(22, 119, 255)");
  expect(confirmButtonChannels).toHaveLength(3);
  expect(Math.max(...confirmButtonChannels) - Math.min(...confirmButtonChannels)).toBeLessThan(20);
  await confirmDialog.locator(".ant-btn-default").click();
  await expect(confirmDialog).toBeHidden();

  await page.getByRole("button", { name: "生成样本" }).click();
  const dialog = page.getByRole("dialog", { name: "开始生成图片" });
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "继续设置" }),
  ).toBeVisible();
  await dialog.getByRole("button", { name: "取 消" }).click();
  await expect(dialog).toBeHidden();

  await page.screenshot({
    path: testInfo.outputPath("dataset-detail-desktop.png"),
    fullPage: true,
  });
});

test("export modal downloads ready historical versions with descriptive filenames", async ({ page }) => {
  const filename = "城市道路车辆样本集-yolo-20260721T0630Z-n128-v002.zip";
  await mockDatasetDetailApi(page, [
    {
      id: "export-2",
      version: 2,
      status: "ready",
      exportFormat: "yolo",
      downloadUrl: "/api/v1/datasets/demo/exports/2/download",
      filename,
      summary: { imageCount: 128, estimatedSizeMb: 24.5 },
      createdAt: "2026-07-21T06:30:00+00:00",
    },
    {
      id: "export-1",
      version: 1,
      status: "running",
      exportFormat: "coco",
      downloadUrl: "/api/v1/datasets/demo/exports/1/download",
      filename: "城市道路车辆样本集-coco-20260720T0530Z-n96-v001.zip",
      summary: { imageCount: 96, estimatedSizeMb: 18.2 },
      createdAt: "2026-07-20T05:30:00+00:00",
    },
  ]);

  await page.goto("/datasets/demo");
  await page.getByRole("button", { name: "训练与导出" }).click();
  await page.getByText("导出数据集", { exact: true }).click();

  const dialog = page.getByRole("dialog").filter({ hasText: "导出历史" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText(filename)).toBeVisible();
  await expect(dialog.getByText("128 张样本")).toBeVisible();
  await expect(dialog.getByText("生成中")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "下载导出版本 v1" })).toBeDisabled();

  const downloadPromise = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "下载导出版本 v2" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe(filename);
});

test("dataset detail remains usable on a narrow viewport", async ({ page }, testInfo: TestInfo) => {
  await mockDatasetDetailApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/datasets/demo");

  await expect(page.getByRole("button", { name: "生成样本" })).toBeVisible();
  await expect(page.getByLabel("按样本来源筛选")).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("dataset-detail-mobile.png"),
    fullPage: true,
  });
});

test("sample pool replaces images when changing pages", async ({ page }) => {
  await mockDatasetDetailApi(page, [], 55);
  await page.goto("/datasets/demo");

  await expect(page.getByText("本页显示第 1–50 张，共 55 张")).toBeVisible();
  await expect(page.getByRole("button", { name: "查看样本 #1 详情" })).toBeVisible();
  await expect(page.getByRole("button", { name: "查看样本 #50 详情" })).toBeVisible();

  await page.locator(".ant-pagination-item-2").click();

  await expect(page.getByText("本页显示第 51–55 张，共 55 张")).toBeVisible();
  await expect(page.getByRole("button", { name: "查看样本 #51 详情" })).toBeVisible();
  await expect(page.getByRole("button", { name: "查看样本 #1 详情" })).toBeHidden();
});

test("image preview only confirms discard after annotations change", async ({ page }) => {
  await mockDatasetDetailApi(page);
  let dialog = await openPreview(page);

  await expect(dialog.getByRole("button", { name: "删除检测框 1" })).toBeVisible();
  await dialog.getByRole("button", { name: "关闭图片详情" }).click();

  await expect(dialog).toBeHidden();
  await expect(page.getByText("放弃标注改动", { exact: true })).toBeHidden();

  dialog = await openPreview(page);
  await dialog.getByRole("button", { name: "删除检测框 1" }).click();
  await dialog.getByRole("button", { name: "关闭图片详情" }).click();

  const discardDialog = page.locator(".ant-modal-confirm").filter({ hasText: "放弃标注改动" });
  await expect(discardDialog).toBeVisible();
  await discardDialog.locator(".ant-btn-default").click();
  await expect(discardDialog).toBeHidden();
  await expect(dialog).toBeVisible();
});

test("desktop image preview is bounded and lets the image use the canvas", async ({ page }, testInfo: TestInfo) => {
  await mockDatasetDetailApi(page);
  await page.setViewportSize({ width: 1440, height: 960 });
  const dialog = await openPreview(page);

  const canvas = dialog.getByRole("region", { name: "图片画布" });
  const inspector = dialog.getByRole("complementary", { name: "图片标注信息" });
  const stage = dialog.getByTestId("image-preview-stage");
  const image = dialog.getByRole("img", { name: promptText });
  await expect.poll(async () => (await stage.boundingBox())?.height ?? 0).toBeGreaterThan(500);
  await expect.poll(async () => (await image.boundingBox())?.width ?? 0).toBeGreaterThan(760);
  const [dialogBox, canvasBox, inspectorBox, imageBox] = await Promise.all([
    dialog.boundingBox(),
    canvas.boundingBox(),
    inspector.boundingBox(),
    image.boundingBox(),
  ]);

  expect(dialogBox).not.toBeNull();
  expect(canvasBox).not.toBeNull();
  expect(inspectorBox).not.toBeNull();
  expect(imageBox).not.toBeNull();
  expect(dialogBox!.width).toBeLessThan(1440);
  expect(dialogBox!.height).toBeLessThan(960);
  expect(canvasBox!.width).toBeGreaterThan(inspectorBox!.width * 2);
  expect(imageBox!.width).toBeGreaterThan(760);
  await expect(stage.getByText("truck", { exact: true })).toBeVisible();
  await dialog.getByRole("region", { name: "检测框 1" }).click();
  await expect(dialog.getByRole("button", { name: "从nw方向缩放检测框 1" })).toBeVisible();
  await expect(page.getByRole("button", { name: "关闭图片详情" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("image-preview-desktop.png"), fullPage: true });
});

test("mobile image preview keeps canvas and inspector usable without overflow", async ({ page }, testInfo: TestInfo) => {
  await mockDatasetDetailApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const dialog = await openPreview(page);

  await expect(dialog.getByRole("region", { name: "图片画布" })).toBeVisible();
  await expect(dialog.getByRole("complementary", { name: "图片标注信息" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "保存标注" })).toBeVisible();
  await expect
    .poll(async () => (await dialog.getByRole("img", { name: promptText }).boundingBox())?.width ?? 0)
    .toBeGreaterThan(250);
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);
  await page.screenshot({ path: testInfo.outputPath("image-preview-mobile.png"), fullPage: true });
});
