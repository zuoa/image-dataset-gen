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

function makeImages() {
  return [1, 2].map((ordinal) => ({
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

async function mockDatasetDetailApi(page: Page) {
  const images = makeImages();
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
    exports: [],
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
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ dataset }) });
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
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  return dialog;
}

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
