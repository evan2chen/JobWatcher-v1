import { expect, test } from "@playwright/test";

import {
  SERVED,
  applicationsInStore,
  card,
  cards,
  facetGroup,
  gotoLanding,
  jw,
  resetStore,
  waitForData,
} from "./helpers";

const closedButton = (page: Parameters<typeof card>[0], title: string) =>
  card(page, title).getByRole("button", { name: "Closed", exact: true });

test.describe("marking a posting closed", () => {
  test.beforeEach(() => resetStore());

  test("reaches the store and the CLI reads the posting as closed", async ({ page }) => {
    await gotoLanding(page, SERVED);
    await expect(cards(page)).toHaveCount(3);

    await closedButton(page, "Compiler Engineer").click();

    await expect(cards(page)).toHaveCount(2);
    await expect(card(page, "Compiler Engineer")).toHaveCount(0);
    await expect
      .poll(() => applicationsInStore().map((r) => [r.posting_id, r.status]), {
        timeout: 10_000,
      })
      .toEqual([["l2", "closed"]]);

    const open = jw("postings", "query", "--open", "--full", "--limit", "0").postings.map((p: any) => p.id);
    expect(open).not.toContain("l2");
    expect(open).toContain("l1");
    expect(jw("postings", "show", "l2", "--full").state).toBe("closed");
  });

  test("a CLI closure shows up in the UI as a closed posting", async ({ page }) => {
    jw("status", "set", "l2", "--status", "closed", "--note", "role filled");

    await gotoLanding(page, SERVED);
    await expect(card(page, "Compiler Engineer")).toHaveCount(0);

    await page.goto(`${SERVED}#/catalog?state=closed`);
    await expect(card(page, "Compiler Engineer")).toBeVisible();
    await expect(closedButton(page, "Compiler Engineer")).toHaveAttribute("aria-pressed", "true");
  });

  test("moves the posting into the closed list and out of the open one", async ({ page }) => {
    await page.goto(`${SERVED}#/catalog`);
    await waitForData(page);
    await expect(cards(page)).toHaveCount(8);

    await closedButton(page, "FPGA Engineer Intern").click();
    await expect(cards(page)).toHaveCount(7);

    await facetGroup(page, "Status").getByRole("button", { name: "closed", exact: true }).click();
    await expect(cards(page)).toHaveCount(3);
    await expect(card(page, "FPGA Engineer Intern")).toBeVisible();
  });

  test("lowers the company's open count", async ({ page }) => {
    await gotoLanding(page, SERVED);
    await closedButton(page, "Compiler Engineer").click();

    await page.goto(`${SERVED}#/company/lumen`);
    await waitForData(page);

    await expect(page.locator("main")).toContainText("1 open · 2 total postings");
  });

  test("can be marked and unmarked from a company's roles", async ({ page }) => {
    await page.goto(`${SERVED}#/company/lumen`);
    await waitForData(page);
    await expect(page.locator("main")).toContainText("2 open · 2 total postings");

    const role = page.locator("details.role").filter({ hasText: "Compiler Engineer" });
    await role.evaluate((el) => ((el as HTMLDetailsElement).open = true));
    const row = role.locator("div.posting").filter({ hasText: "Compiler Engineer" });
    const button = row.getByRole("button", { name: "Closed", exact: true });

    await button.click();

    await expect(button).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("main")).toContainText("1 open · 2 total postings");
    await expect
      .poll(() => applicationsInStore().map((r) => [r.posting_id, r.status]), {
        timeout: 10_000,
      })
      .toEqual([["l2", "closed"]]);

    await button.click();

    await expect(button).toHaveAttribute("aria-pressed", "false");
    await expect(page.locator("main")).toContainText("2 open · 2 total postings");
    await expect.poll(() => applicationsInStore().length, { timeout: 10_000 }).toBe(0);
  });

  test("a posting the feed already closed has no closed button", async ({ page }) => {
    await page.goto(`${SERVED}#/company/zenith`);
    await waitForData(page);

    const role = page.locator("details.role").filter({ hasText: "Platform Engineer Intern" });
    await role.evaluate((el) => ((el as HTMLDetailsElement).open = true));

    await expect(role.locator("div.posting")).toHaveCount(1);
    await expect(role.getByRole("button", { name: "Closed", exact: true })).toHaveCount(0);
  });

  test("unmarking a closed posting reopens it", async ({ page }) => {
    await gotoLanding(page, SERVED);
    await closedButton(page, "Compiler Engineer").click();
    await expect.poll(() => applicationsInStore().length, { timeout: 10_000 }).toBe(1);

    await page.goto(`${SERVED}#/catalog?state=closed`);
    await closedButton(page, "Compiler Engineer").click();
    await expect.poll(() => applicationsInStore().length, { timeout: 10_000 }).toBe(0);

    await page.goto(SERVED);
    await waitForData(page);
    await expect(card(page, "Compiler Engineer")).toBeVisible();
  });
});
