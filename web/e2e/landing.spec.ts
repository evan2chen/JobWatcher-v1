import { expect, test } from "@playwright/test";

import { SERVED, card, cards, gotoLanding, resetStore, waitForData } from "./helpers";

test.describe("landing", () => {
  test.beforeEach(() => resetStore());

  test("shows the Software Engineering matches by default", async ({ page }) => {
    await gotoLanding(page, SERVED);

    await expect(page.locator("main h1")).toHaveText("Must apply");
    await expect(page.locator("main p.muted").first())
      .toContainText("3 open roles match your Software Engineering profile");
    await expect(cards(page)).toHaveCount(3);
  });

  test("excludes a title caught by the profile's exclude list", async ({ page }) => {
    await gotoLanding(page, SERVED);

    await expect(card(page, "Sales Engineer Intern")).toHaveCount(0);
  });

  test("ranks the highest-scoring posting first", async ({ page }) => {
    await gotoLanding(page, SERVED);

    await expect(cards(page).first()).toContainText("Software Engineer Intern");
    await expect(cards(page).first()).toContainText("offers sponsorship");
    await expect(cards(page).first()).toContainText("new this week");
  });

  test("switching profiles changes the matched set", async ({ page }) => {
    await gotoLanding(page, SERVED);

    await page.getByRole("tab", { name: "ML / AI Research" }).click();
    await expect(cards(page)).toHaveCount(1);
    await expect(card(page, "Machine Learning Research Intern")).toBeVisible();

    await page.getByRole("tab", { name: "Hardware / Embedded" }).click();
    await expect(cards(page)).toHaveCount(1);
    await expect(card(page, "FPGA Engineer Intern")).toBeVisible();
  });

  test("a profile with no matches explains itself", async ({ page }) => {
    await gotoLanding(page, SERVED);

    await page.getByRole("tab", { name: "ML / AI Research" }).click();
    await card(page, "Machine Learning Research Intern")
      .getByRole("button", { name: "Skip", exact: true })
      .click();

    await expect(page.locator("p.empty")).toContainText("Nothing open matches this profile");
    await expect(cards(page)).toHaveCount(0);
  });

  test("the catalog link carries no filters", async ({ page }) => {
    await gotoLanding(page, SERVED);

    await page.getByRole("link", { name: "browse the full catalog" }).click();
    await waitForData(page);

    await expect(page.locator("main h1")).toHaveText("Catalog");
    await expect(cards(page)).toHaveCount(8);
  });
});

test.describe("company page", () => {
  test.beforeEach(() => resetStore());

  test("lists a company's postings grouped by role", async ({ page }) => {
    await page.goto(`${SERVED}#/company/zenith`);
    await waitForData(page);

    await expect(page.locator("main h1")).toHaveText("Zenith");
    await expect(page.locator("p.muted.small").first()).toContainText("3 open · 4 total postings");
    await expect(page.locator(".posting")).toHaveCount(4);
    await expect(page.locator("details.role")).toHaveCount(4);
  });

  test("the timeline tab renders the events.jsonl the page fetched at mount", async ({ page }) => {
    const events = page.waitForResponse((r) =>
      r.url().includes("/tracker/companies/zenith/events.jsonl"),
    );
    await page.goto(`${SERVED}#/company/zenith`);
    await waitForData(page);
    expect((await events).status()).toBe(200);

    await page.getByRole("tab", { name: "Timeline" }).click();

    await expect(page.locator(".tabs button[aria-selected=true]")).toHaveText("Timeline");
    await expect(page.locator("li.tl-item")).toHaveCount(4);
    await expect(page.locator("li.tl-item .tl-type").first()).toHaveText("opened");
  });

  test("an untracked slug does not crash the app", async ({ page }) => {
    await page.goto(`${SERVED}#/company/nope`);
    await expect(page.locator("p.loading")).toHaveCount(0, { timeout: 15_000 });

    await expect(page.locator("main")).toBeVisible();
    await expect(page.locator("main")).not.toBeEmpty();
  });
});
