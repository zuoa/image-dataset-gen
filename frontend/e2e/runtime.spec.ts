import { expect, test } from "@playwright/test";

const contentSecurityPolicy = [
  "default-src 'self'",
  "img-src 'self' data: blob:",
  "connect-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "script-src 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
].join("; ");

test("authenticated app loads under the production CSP", async ({ page }) => {
  const browserErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));

  await page.route("**/*", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;

    if (pathname === "/api/v1/auth/refresh") {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          token: "e2e-token",
          user: { id: "e2e-user", username: "e2e", plan: "pro" },
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

    const response = await route.fetch();
    if (request.resourceType() === "document") {
      await route.fulfill({
        response,
        headers: {
          ...response.headers(),
          "content-security-policy": contentSecurityPolicy,
        },
      });
      return;
    }
    await route.fulfill({ response });
  });

  await page.goto("/");

  await expect(page.getByRole("heading", { name: "数据集管理" })).toBeVisible();
  expect(browserErrors).toEqual([]);
});
