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

function makeImages(count = imageCount) {
  return Array.from({ length: count }, (_, index) => ({
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

async function mockWorkbenchApi(
  page: Page,
  options: { segmentAssist?: boolean; rotateTokenOnPredict?: boolean; sessionCreateDelayMs?: number } = {},
) {
  let images = makeImages();
  let refreshCount = 0;
  let segmentCreateCount = 0;
  let segmentDeleteCount = 0;

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
    segmentAssistAvailable: options.segmentAssist ?? false,
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
      refreshCount += 1;
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          token: `e2e-token-${refreshCount}`,
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

    const segmentSessionMatch = url.pathname.match(
      /^\/api\/v1\/datasets\/demo\/images\/(image-\d+)\/segment-assist\/sessions$/,
    );
    if (request.method() === "POST" && segmentSessionMatch) {
      segmentCreateCount += 1;
      if (options.sessionCreateDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, options.sessionCreateDelayMs));
      }
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          sessionId: `signed-${segmentSessionMatch[1]}`,
          imageWidth: 960,
          imageHeight: 640,
          expiresIn: 600,
          model: "sam2.1_hiera_small",
        }),
      });
      return;
    }

    const segmentPredictMatch = url.pathname.match(
      /^\/api\/v1\/datasets\/demo\/images\/(image-\d+)\/segment-assist\/sessions\/[^/]+\/predict$/,
    );
    if (request.method() === "POST" && segmentPredictMatch) {
      if (
        options.rotateTokenOnPredict
        && request.headers()["authorization"] === "Bearer e2e-token-1"
      ) {
        await route.fulfill({
          status: 401,
          contentType: "application/json",
          body: JSON.stringify({ message: "access token expired" }),
        });
        return;
      }
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          bbox: [0.49, 0.6, 0.64, 0.48],
          maskDataUrl: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADElEQVR42mNk+M/wHwAF/gL+XDYbGQAAAABJRU5ErkJggg==",
          maskScore: 0.93,
        }),
      });
      return;
    }

    const segmentDeleteMatch = url.pathname.match(
      /^\/api\/v1\/datasets\/demo\/images\/(image-\d+)\/segment-assist\/sessions\/[^/]+$/,
    );
    if (request.method() === "DELETE" && segmentDeleteMatch) {
      segmentDeleteCount += 1;
      await route.fulfill({ status: 204 });
      return;
    }

    await route.abort();
  });

  return {
    refreshCount: () => refreshCount,
    segmentCreateCount: () => segmentCreateCount,
    segmentDeleteCount: () => segmentDeleteCount,
  };
}

async function mockPaginatedWorkbenchApi(page: Page) {
  let images = makeImages(101).map((image) => ({ ...image, annotationStatus: "pending" }));
  const requestedCursors: string[] = [];

  const dataset = (
    pageImages: ReturnType<typeof makeImages>,
    nextCursor: string | null,
    filteredTotal = images.length,
  ) => ({
    id: "demo",
    name: "分页标注数据集",
    description: "用于验证标注队列分页前进",
    categories: ["truck", "wheel", "person"],
    status: "ready",
    imageCount: images.length,
    selectedCount: images.length,
    taskCount: 0,
    spentCost: 0,
    annotation: {},
    segmentAssistAvailable: false,
    images: pageImages,
    imagesTotal: filteredTotal,
    imagesNextCursor: nextCursor,
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
      const cursor = url.searchParams.get("images_cursor");
      if (cursor) requestedCursors.push(cursor);
      const cursorOrdinal = cursor ? Number(cursor.replace("image-", "")) : null;
      const cursorOffset = cursorOrdinal === null
        ? -1
        : filteredImages.findIndex((image) => image.ordinal > cursorOrdinal);
      const offset = cursorOrdinal !== null
        ? cursorOffset >= 0 ? cursorOffset : filteredImages.length
        : Number(url.searchParams.get("images_offset") ?? 0);
      const limit = Number(url.searchParams.get("images_limit") ?? 100);
      const pageImages = filteredImages.slice(offset, offset + limit);
      const nextCursor = offset + pageImages.length < filteredImages.length
        ? pageImages[pageImages.length - 1]?.id ?? null
        : null;
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ dataset: dataset(pageImages, nextCursor, filteredImages.length) }),
      });
      return;
    }

    const annotationMatch = url.pathname.match(/^\/api\/v1\/datasets\/demo\/images\/(image-\d+)\/annotations$/);
    if (request.method() === "PATCH" && annotationMatch) {
      const payload = request.postDataJSON() as {
        detections: Array<{ category: string; confidence: number; bbox: [number, number, number, number] }>;
      };
      const updatedImage = {
        ...images.find((image) => image.id === annotationMatch[1])!,
        detections: payload.detections,
        annotationStatus: payload.detections.length > 0 ? "annotated" : "empty",
      };
      images = images.map((image) => (image.id === updatedImage.id ? updatedImage : image));
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ dataset: dataset([], null), image: updatedImage }),
      });
      return;
    }

    await route.abort();
  });

  return { requestedCursors: () => requestedCursors };
}

test("smart select previews a mask, accepts correction points, and confirms a regular box", async ({ page }) => {
  const api = await mockWorkbenchApi(page, { segmentAssist: true, rotateTokenOnPredict: true });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/datasets/demo/annotate");

  const smartSelect = page.getByRole("button", { name: "智能点选", exact: true });
  await expect(smartSelect).toBeVisible();
  await expect(smartSelect).toHaveAttribute("aria-pressed", "false");

  const viewport = page.getByTestId("annotation-viewport");
  await viewport.click({ position: { x: 450, y: 330 } });
  expect(api.segmentCreateCount()).toBe(0);

  await page.keyboard.press("s");
  await expect(smartSelect).toHaveAttribute("aria-pressed", "true");
  await viewport.click({ position: { x: 450, y: 330 } });
  const confirmCandidate = page.getByRole("button", { name: "确认智能候选框" });
  await expect(confirmCandidate).toBeEnabled();
  await expect.poll(api.refreshCount).toBe(2);
  expect(api.segmentDeleteCount()).toBe(0);
  await expect(page.locator('img[src^="data:image/png;base64,"]')).toBeVisible();

  await page.getByRole("button", { name: "添加排除点" }).click();
  await viewport.click({ position: { x: 700, y: 320 } });
  await expect(confirmCandidate).toBeEnabled();
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.press("Enter");
  await expect(confirmCandidate).toBeEnabled();
  await expect(smartSelect).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("a");

  await expect(page.getByRole("button", { name: "选择检测框 3，类别 truck" })).toBeAttached();
  await expect(smartSelect).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByRole("button", { name: "取消智能候选框" })).toBeHidden();
  await expect.poll(api.segmentDeleteCount).toBe(1);

  await viewport.click({ position: { x: 450, y: 330 } });
  expect(api.segmentCreateCount()).toBe(1);
});

test("leaving during session creation deletes the late GPU session", async ({ page }) => {
  const api = await mockWorkbenchApi(page, { segmentAssist: true, sessionCreateDelayMs: 300 });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/datasets/demo/annotate");

  await expect(page.getByRole("button", { name: "智能点选", exact: true })).toBeVisible();
  await page.keyboard.press("s");
  await page.getByTestId("annotation-viewport").click({ position: { x: 450, y: 330 } });
  await expect.poll(api.segmentCreateCount).toBe(1);
  await page.getByRole("link", { name: "返回数据集" }).click();
  await expect(page).toHaveURL(/\/datasets\/demo$/);
  await expect.poll(api.segmentDeleteCount).toBe(1);
});

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

test("save and next loads the next page at the queue boundary", async ({ page }) => {
  const api = await mockPaginatedWorkbenchApi(page);
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/datasets/demo/annotate");

  const queue = page.getByRole("region", { name: "标注队列" });
  const image100Button = queue.locator("button").filter({ hasText: "#100" });
  await expect(image100Button).toBeAttached();
  await image100Button.evaluate((element: HTMLButtonElement) => element.click());
  await expect(page.getByText("样本 #100", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "保存并下一张" }).click();

  await expect(page.getByText("样本 #101", { exact: true })).toBeVisible();
  await expect(page.getByText("101/101", { exact: true })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("标注已保存，已进入下一张");
  await expect.poll(api.requestedCursors).toEqual(["image-100"]);
});

test("save and next loads the next pending image when the saved image leaves the filtered queue", async ({ page }) => {
  const api = await mockPaginatedWorkbenchApi(page);
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/datasets/demo/annotate");

  const queue = page.getByRole("region", { name: "标注队列" });
  await queue
    .getByRole("radiogroup", { name: "筛选标注队列" })
    .getByText("待处理", { exact: true })
    .click();
  await expect(queue.getByText("101 张待处理", { exact: true })).toBeVisible();
  const image100Button = queue.locator("button").filter({ hasText: "#100" });
  await expect(image100Button).toBeAttached();
  await image100Button.evaluate((element: HTMLButtonElement) => element.click());
  await expect(page.getByText("样本 #100", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "保存并下一张" }).click();

  await expect(page.getByText("样本 #101", { exact: true })).toBeVisible();
  await expect(page.getByText("100/100", { exact: true })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("标注已保存，已进入下一张待处理图片");
  await expect.poll(api.requestedCursors).toEqual(["image-100"]);
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
