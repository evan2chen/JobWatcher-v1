import { expect, test } from "@playwright/test";

import {
  STATIC,
  applicationsInStore,
  card,
  gotoLanding,
  resetStore,
  syncNote,
  waitForData,
} from "./helpers";

test.describe("static host, no API", () => {
  test.beforeEach(() => resetStore());

  test("loads tracker data over relative paths from /docs/", async ({ page }) => {
    await gotoLanding(page, STATIC);

    await expect(page.locator("main h1")).toHaveText("Must apply");
    await expect(page.locator(".site-footer")).toContainText("data: local");
    await expect(page.locator("article.posting-card")).toHaveCount(3);
  });

  test("says marks are browser-only", async ({ page }) => {
    await gotoLanding(page, STATIC);

    await expect(syncNote(page)).toHaveText(/marks saved in this browser only/);
    await expect(syncNote(page)).not.toHaveClass(/is-error/);
  });

  test("the probe 404s and is not retried as an error", async ({ page }) => {
    const probes: number[] = [];
    page.on("response", (res) => {
      if (res.url().includes("/api/health")) probes.push(res.status());
    });

    await gotoLanding(page, STATIC);
    await expect(syncNote(page)).toHaveText(/browser only/);

    expect(probes.every((s) => s === 404)).toBe(true);
    await expect(page.locator("p.error")).toHaveCount(0);
  });

  test("a mark survives a reload via localStorage and never reaches the store", async ({ page }) => {
    await gotoLanding(page, STATIC);

    const target = card(page, "Software Engineer Intern");
    await target.getByRole("button", { name: "Interested", exact: true }).click();
    await expect(target.getByRole("button", { name: "Interested", exact: true }))
      .toHaveAttribute("aria-pressed", "true");

    const stored = await page.evaluate(() => window.localStorage.getItem("jw-status"));
    expect(stored).toContain("z1");

    await page.reload();
    await waitForData(page);

    await expect(
      card(page, "Software Engineer Intern")
        .getByRole("button", { name: "Interested", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");

    expect(applicationsInStore()).toHaveLength(0);
  });

  test("an applied posting drops off the landing list on reload", async ({ page }) => {
    await gotoLanding(page, STATIC);
    await expect(page.locator("article.posting-card")).toHaveCount(3);

    await card(page, "Compiler Engineer")
      .getByRole("button", { name: "Applied", exact: true })
      .click();

    await page.reload();
    await waitForData(page);

    await expect(page.locator("article.posting-card")).toHaveCount(2);
    await expect(page.locator(".tracking-line")).toContainText("1 application");
  });

  test("a closed mark hides the posting from the open lists and survives a reload", async ({ page }) => {
    await gotoLanding(page, STATIC);
    await expect(page.locator("article.posting-card")).toHaveCount(3);

    await card(page, "Compiler Engineer")
      .getByRole("button", { name: "Closed", exact: true })
      .click();
    await expect(page.locator("article.posting-card")).toHaveCount(2);

    await page.reload();
    await waitForData(page);

    await expect(page.locator("article.posting-card")).toHaveCount(2);
    await expect(card(page, "Compiler Engineer")).toHaveCount(0);
    expect(applicationsInStore()).toHaveLength(0);
  });
});
