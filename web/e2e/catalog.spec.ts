import { expect, test } from "@playwright/test";

import { SERVED, card, cards, facetGroup, resetStore, waitForData } from "./helpers";

const CATALOG = `${SERVED}#/catalog`;

test.describe("catalog", () => {
  test.beforeEach(() => resetStore());

  test("renders the whole corpus and counts it", async ({ page }) => {
    await page.goto(CATALOG);
    await waitForData(page);

    await expect(page.locator("main h1")).toHaveText("Catalog");
    await expect(page.locator(".page-head")).toContainText("10 postings across 5 companies");
    await expect(cards(page)).toHaveCount(8);
  });

  test("free-text search narrows the list and lands in the hash", async ({ page }) => {
    await page.goto(CATALOG);
    await waitForData(page);

    await page.getByLabel("Search postings").fill("compiler");

    await expect(cards(page)).toHaveCount(1);
    await expect(card(page, "Compiler Engineer")).toBeVisible();
    await expect.poll(() => page.evaluate(() => location.hash)).toContain("q=compiler");
  });

  test("location search matches inside the location list", async ({ page }) => {
    await page.goto(CATALOG);
    await waitForData(page);

    await page.getByLabel("Filter by location").fill("remote");

    await expect(cards(page)).toHaveCount(2);
    await expect.poll(() => page.evaluate(() => location.hash)).toContain("loc=remote");
  });

  test("the state filter reaches closed postings", async ({ page }) => {
    await page.goto(CATALOG);
    await waitForData(page);

    await facetGroup(page, "Status").getByRole("button", { name: "closed", exact: true }).click();

    await expect(cards(page)).toHaveCount(2);
    await expect(card(page, "Platform Engineer Intern")).toBeVisible();
    await expect.poll(() => page.evaluate(() => location.hash)).toContain("state=closed");
  });

  test("a category facet filters and reports its count", async ({ page }) => {
    await page.goto(CATALOG);
    await waitForData(page);

    await facetGroup(page, "Category").getByRole("checkbox", { name: /^Quant/ }).check();

    await expect(cards(page)).toHaveCount(1);
    await expect(card(page, "Quantitative Trader Intern")).toBeVisible();
    await expect.poll(() => page.evaluate(() => location.hash)).toContain("cat=Quant");
  });

  test("a deep link applies its filters on first paint", async ({ page }) => {
    await page.goto(`${SERVED}#/catalog?cat=Software&lvl=new-grad`);
    await waitForData(page);

    await expect(cards(page)).toHaveCount(2);
    await expect(card(page, "Backend Engineer, New Grad")).toBeVisible();
    await expect(card(page, "Compiler Engineer")).toBeVisible();
  });

  test("the companies view groups by tier", async ({ page }) => {
    await page.goto(CATALOG);
    await waitForData(page);

    await page.getByRole("tab", { name: "Companies" }).click();

    await expect(page.locator("section.tier-group")).toHaveCount(3);
    await expect(page.locator(".tier-heading").first()).toContainText("S");
    await expect.poll(() => page.evaluate(() => location.hash)).toContain("view=companies");
  });

  test("the mark facet filters on what the browser has marked", async ({ page }) => {
    await page.goto(CATALOG);
    await waitForData(page);

    await card(page, "FPGA Engineer Intern")
      .getByRole("button", { name: "Applied", exact: true })
      .click();

    await facetGroup(page, "My marks")
      .getByRole("button", { name: "Unmarked", exact: true })
      .click();

    await expect(cards(page)).toHaveCount(7);
    await expect(card(page, "FPGA Engineer Intern")).toHaveCount(0);
  });

  test("a posting links through to its company page", async ({ page }) => {
    await page.goto(CATALOG);
    await waitForData(page);

    await card(page, "Quantitative Trader Intern").locator("a.pc-company").click();
    await waitForData(page);

    await expect(page.locator("main h1")).toHaveText("Orbit Capital");
    await expect.poll(() => page.evaluate(() => location.hash)).toBe("#/company/orbit");
  });
});
