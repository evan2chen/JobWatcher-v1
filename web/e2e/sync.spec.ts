import { expect, test } from "@playwright/test";

import {
  SERVED,
  applicationsInStore,
  card,
  gotoLanding,
  resetStore,
  seedLocalStorage,
  syncNote,
  waitForData,
} from "./helpers";

test.describe("served with the write API", () => {
  test.beforeEach(() => resetStore());

  test("switches to server mode once the probe answers", async ({ page }) => {
    await gotoLanding(page, SERVED);

    await expect(syncNote(page)).toHaveText(/marks sync to this host/);
    await expect(syncNote(page)).not.toHaveClass(/is-error/);
  });

  test("a mark reaches the store and is visible to the CLI", async ({ page }) => {
    await gotoLanding(page, SERVED);

    await card(page, "Compiler Engineer")
      .getByRole("button", { name: "Applied", exact: true })
      .click();

    await expect
      .poll(() => applicationsInStore().map((r) => [r.posting_id, r.status]), {
        timeout: 10_000,
      })
      .toEqual([["l2", "applied"]]);
  });

  test("the mark comes back from the server, not from localStorage", async ({ page }) => {
    await gotoLanding(page, SERVED);

    await card(page, "Software Engineer Intern")
      .getByRole("button", { name: "Interested", exact: true })
      .click();
    await expect.poll(() => applicationsInStore().length, { timeout: 10_000 }).toBe(1);

    await page.evaluate(() => window.localStorage.removeItem("jw-status"));
    await page.reload();
    await waitForData(page);

    await expect(
      card(page, "Software Engineer Intern")
        .getByRole("button", { name: "Interested", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  test("toggling a mark off deletes the record", async ({ page }) => {
    await gotoLanding(page, SERVED);

    const button = card(page, "Backend Engineer, New Grad")
      .getByRole("button", { name: "Interested", exact: true });

    await button.click();
    await expect(button).toHaveAttribute("aria-pressed", "true");
    await expect.poll(() => applicationsInStore().length, { timeout: 10_000 }).toBe(1);

    await button.click();
    await expect(button).toHaveAttribute("aria-pressed", "false");
    await expect.poll(() => applicationsInStore().length, { timeout: 10_000 }).toBe(0);
  });

  test("marks already in localStorage are adopted into the store exactly once", async ({ page }) => {
    await seedLocalStorage(page, {
      "jw-status": { z1: { status: "applied", at: 1 }, o2: { status: "skipped", at: 2 } },
    });
    await gotoLanding(page, SERVED);

    await expect
      .poll(() => applicationsInStore().map((r) => r.posting_id).sort(), { timeout: 10_000 })
      .toEqual(["o2", "z1"]);
    await expect
      .poll(() => page.evaluate(() => window.localStorage.getItem("jw-adopted")))
      .toBe("true");

    await page.evaluate(() => {
      window.localStorage.setItem(
        "jw-status",
        JSON.stringify({ l2: { status: "applied", at: 3 } }),
      );
    });
    await page.reload();
    await waitForData(page);

    await expect
      .poll(() => applicationsInStore().map((r) => r.posting_id).sort(), { timeout: 10_000 })
      .toEqual(["o2", "z1"]);
  });

  test("a failed write rolls the mark back and surfaces the error", async ({ page }) => {
    await gotoLanding(page, SERVED);
    await expect(syncNote(page)).toHaveText(/marks sync to this host/);

    await page.route("**/api/applications/**", (route) =>
      route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ ok: false, error: "disk on fire" }),
      }),
    );

    const button = card(page, "Software Engineer Intern")
      .getByRole("button", { name: "Interested", exact: true });
    await button.click();

    await expect(syncNote(page)).toHaveClass(/is-error/);
    await expect(syncNote(page)).toContainText(/status did not save/);
    await expect(button).toHaveAttribute("aria-pressed", "false");

    expect(applicationsInStore()).toHaveLength(0);
  });

  test("the active profile choice is remembered server-side", async ({ page }) => {
    await gotoLanding(page, SERVED);

    const saved = page.waitForResponse(
      (r) => r.url().includes("/api/settings/active_profile") && r.request().method() === "PUT",
    );
    await page.getByRole("tab", { name: "Quant / Trading" }).click();
    await expect(card(page, "Quantitative Trader Intern")).toBeVisible();
    expect((await saved).status()).toBe(200);

    await page.evaluate(() => window.localStorage.clear());
    await page.reload();
    await waitForData(page);

    await expect(page.getByRole("tab", { name: "Quant / Trading" }))
      .toHaveAttribute("aria-selected", "true");
    await expect(card(page, "Quantitative Trader Intern")).toBeVisible();
  });

  test("a profile edit is persisted server-side", async ({ page }) => {
    await gotoLanding(page, SERVED);
    await expect(page.locator("article.posting-card")).toHaveCount(3);

    await page.getByRole("button", { name: "Edit", exact: true }).click();

    const saved = page.waitForResponse(
      (r) => r.url().includes("/api/profiles/") && r.request().method() === "PUT",
    );
    await page.getByRole("button", { name: "new-grad", exact: true }).click();

    await expect(page.locator("article.posting-card")).toHaveCount(2);
    await expect(card(page, "Software Engineer Intern")).toHaveCount(0);
    await expect(syncNote(page)).not.toHaveClass(/is-error/);
    expect((await saved).status()).toBe(200);

    await page.evaluate(() => window.localStorage.clear());
    await page.reload();
    await waitForData(page);

    await expect(page.locator("article.posting-card")).toHaveCount(2);
    await expect(page.getByRole("button", { name: "Edit", exact: true })).toBeVisible();
  });
});
