import { expect, test, type Page, type TestInfo } from "@playwright/test";

const imageCount = 18;

function previewSvg(index: number) {
  const hue = 205 + (index % 4) * 8;
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="960" height="640" viewBox="0 0 960 640">
      <defs>
        <linearGradient id="sky" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stop-color="hsl(${hue} 45% 42%)" />
          <stop offset="1" stop-color="#d8c9ad" />
        </linearGradient>
      </defs>
      <rect width="960" height="640" fill="url(#sky)" />
      <rect y="430" width="960" height="210" fill="#334155" />
      <rect x="160" y="310" width="610" height="190" rx="34" fill="#e2e8f0" />
      <rect x="520" y="250" width="190" height="160" rx="28" fill="#cbd5e1" />
      <rect x="548" y="275" width="125" height="85" rx="14" fill="#31536d" />
      <circle cx="300" cy="510" r="66" fill="#111827" />
      <circle cx="300" cy="510" r="30" fill="#94a3b8" />
      <circle cx="660" cy="510" r="66" fill="#111827" />
      <circle cx="660" cy="510" r="30" fill="#94a3b8" />
      <text x="42" y="70" fill="white" font-family="system-ui" font-size="28">Sample ${index + 1}</text>
    </svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

function makeImages() {
  return Array.from({ length: imageCount }, (_, index) => ({
    id: `image-${index + 1}`,
    datasetId: "demo",
    sourceType: index % 3 === 0 ? "generated" : "imported",
    sourceOrdinal: index + 1,
    ordinal: index + 1,
    status: "completed",
    latencyMs: 420,
    seed: 1000 + index,
    promptText: `道路上的配送车辆，样本 ${index + 1}`,
    diversityVars: {},
    previewSvg: previewSvg(index),
    selected: true,
    annotationStatus: index < 8 ? "annotated" : "pending",
    confidenceScore: 0.92,
    source: index % 3 === 0 ? "generation" : "imported",
    split: index % 5 === 0 ? "val" : "train",
    detections:
      index < 8
        ? [
            { category: "truck", confidence: 0.94, bbox: [0.49, 0.6, 0.64, 0.48] },
            { category: "wheel", confidence: 0.88, bbox: [0.31, 0.8, 0.14, 0.2] },
          ]
        : [{ category: "truck", confidence: 0.78, bbox: [0.49, 0.6, 0.64, 0.48] }],
  }));
}

async function mockWorkbenchApi(page: Page) {
  let images = makeImages();

  const dataset = () => ({
    id: "demo",
    name: "城市道路车辆样本集",
    description: "用于配送车辆识别的演示数据集",
    categories: ["truck", "wheel", "person"],
    status: "ready",
    imageCount,
    selectedCount: imageCount,
    taskCount: 1,
    spentCost: 1.24,
    annotation: {},
    images,
    imagesTotal: imageCount,
    imagesNextCursor: null,
    imageAnnotationCounts: {
      annotated: images.filter((image) => image.annotationStatus === "annotated" || image.annotationStatus === "empty").length,
      unannotated: images.filter((image) => image.annotationStatus !== "annotated" && image.annotationStatus !== "empty").length,
    },
    tasks: [],
    exports: [],
    latestTask: null,
  });

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
      const annotationFilter = url.searchParams.get("filter_annotation");
      const filteredImages = annotationFilter
        ? images.filter((image) => {
            const processed = image.annotationStatus === "annotated" || image.annotationStatus === "empty";
            return annotationFilter === "annotated" ? processed : !processed;
          })
        : images;
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ dataset: { ...dataset(), images: filteredImages, imagesTotal: filteredImages.length } }),
      });
      return;
    }

    const annotationMatch = url.pathname.match(/^\/api\/v1\/datasets\/demo\/images\/(image-\d+)\/annotations$/);
    if (request.method() === "PATCH" && annotationMatch) {
      const payload = request.postDataJSON() as { detections: Array<{ category: string; confidence: number; bbox: [number, number, number, number] }> };
      const updatedImage = {
        ...images.find((image) => image.id === annotationMatch[1])!,
        detections: payload.detections,
        annotationStatus: payload.detections.length > 0 ? "annotated" : "empty",
      };
      images = images.map((image) => (image.id === updatedImage.id ? updatedImage : image));
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ dataset: dataset(), image: updatedImage }),
      });
      return;
    }

    await route.abort();
  });
}

async function expectNoHorizontalOverflow(page: Page) {
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);
}

test("desktop workbench keeps queue, canvas, and inspector in separate columns", async ({ page }, testInfo: TestInfo) => {
  await mockWorkbenchApi(page);
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/datasets/demo/annotate");

  const queue = page.getByRole("region", { name: "标注队列" });
  const canvas = page.locator("#annotation-canvas");
  const inspector = page.getByRole("complementary", { name: "标注检查器" });
  await expect(queue).toBeVisible();
  await expect(canvas).toBeVisible();
  await expect(inspector).toBeVisible();

  const [queueBox, canvasBox, inspectorBox] = await Promise.all([
    queue.boundingBox(),
    canvas.boundingBox(),
    inspector.boundingBox(),
  ]);
  expect(queueBox).not.toBeNull();
  expect(canvasBox).not.toBeNull();
  expect(inspectorBox).not.toBeNull();
  expect(queueBox!.x + queueBox!.width).toBeLessThanOrEqual(canvasBox!.x + 1);
  expect(canvasBox!.x + canvasBox!.width).toBeLessThanOrEqual(inspectorBox!.x + 1);
  await expectNoHorizontalOverflow(page);

  await page.getByRole("button", { name: "对象 1", exact: true }).click();
  const resizeHandle = page.getByRole("button", { name: "从nw方向缩放检测框 1" });
  await expect(resizeHandle).toBeVisible();
  const resizeHandleBox = await resizeHandle.boundingBox();
  expect(resizeHandleBox?.width).toBeGreaterThanOrEqual(44);
  expect(resizeHandleBox?.height).toBeGreaterThanOrEqual(44);
  await page.screenshot({ path: testInfo.outputPath("annotation-selected-box.png"), fullPage: true });
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.press("Escape");

  const addBoxButton = page.getByRole("button", { name: "新增框", exact: true });
  await addBoxButton.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("样本 #1", { exact: true })).toBeVisible();
  await page.keyboard.press("Enter");
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());

  await page.screenshot({ path: testInfo.outputPath("annotation-desktop.png"), fullPage: true });

  await page.getByRole("button", { name: "标记为空" }).click();
  await expect(page.getByText("样本 #2", { exact: true })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("标注已保存，已进入下一张");
});

test("tablet and mobile expose queue and inspector as on-demand drawers", async ({ page }, testInfo: TestInfo) => {
  await mockWorkbenchApi(page);
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/datasets/demo/annotate");

  await expect(page.getByRole("region", { name: "标注队列" })).toBeHidden();
  await expect(page.getByRole("complementary", { name: "标注检查器" })).toBeHidden();
  await page.getByRole("button", { name: "打开标注队列" }).click();
  await expect(page.getByRole("region", { name: "标注队列" })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "检查器" }).click();
  await expect(page.getByRole("complementary", { name: "标注检查器" })).toBeVisible();
  await page.waitForTimeout(350);
  await page.screenshot({ path: testInfo.outputPath("annotation-tablet.png"), fullPage: true });

  await page.keyboard.press("Escape");
  await expect(page.getByRole("complementary", { name: "标注检查器" })).toBeHidden();
  await page.waitForTimeout(350);
  await page.setViewportSize({ width: 390, height: 844 });
  await expectNoHorizontalOverflow(page);
  await expect(page.getByRole("button", { name: "打开标注队列" })).toBeVisible();
  await expect(page.getByRole("button", { name: "检查器" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("annotation-mobile.png"), fullPage: true });

  await page.getByRole("button", { name: "检查器" }).click();
  await expect(page.getByRole("complementary", { name: "标注检查器" })).toBeVisible();
  await page.waitForTimeout(350);
  await page.screenshot({ path: testInfo.outputPath("annotation-mobile-inspector.png"), fullPage: true });
});
