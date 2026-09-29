import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "@playwright/test";

import { SERVED, card, resetStore, waitForData } from "./helpers";
import { FIXTURE } from "./playwright.config";
import type { RawPosting } from "../src/lib/types";

const SLIM_KEYS: Array<keyof RawPosting> = [
  "id", "co", "rk", "lvl", "t", "tm", "loc", "u",
  "pa", "fs", "ls", "ca", "s", "cat", "sp", "deg",
];

type Corpus = { generated_at: number; count: number; postings: RawPosting[] };

const corpus = (): Corpus =>
  JSON.parse(
    readFileSync(join(FIXTURE.root, "tracker", "all_postings.json"), "utf-8"),
  ) as Corpus;

test.describe("read model contract", () => {
  test.beforeEach(() => resetStore());

  test("the reconciler emits exactly the keys the decoder reads", () => {
    const { postings } = corpus();
    expect(postings.length).toBeGreaterThan(0);

    for (const raw of postings) {
      expect(Object.keys(raw).sort()).toEqual([...SLIM_KEYS].sort());
    }
  });

  test("the aggregate agrees with its own count and the index", () => {
    const { count, postings } = corpus();
    expect(count).toBe(postings.length);

    const index = JSON.parse(
      readFileSync(join(FIXTURE.root, "tracker", "index.json"), "utf-8"),
    ) as { companies: Array<{ slug: string; posting_count: number }> };

    for (const company of index.companies) {
      const mine = postings.filter((p) => p.co === company.slug);
      expect(mine).toHaveLength(company.posting_count);
    }
  });

  test("every decoded field reaches the rendered card", async ({ page }) => {
    const z1 = corpus().postings.find((p) => p.id === "z1");
    expect(z1).toBeDefined();

    await page.goto(`${SERVED}#/catalog?q=software+engineer+intern`);
    await waitForData(page);

    const target = card(page, "Software Engineer Intern");
    await expect(target).toHaveCount(1);

    await expect(target.locator("h3.pc-title")).toHaveText(`${z1!.t} ↗`);
    await expect(target.locator(".pc-meta")).toContainText(z1!.tm[0]);
    await expect(target.locator(".pc-meta")).toContainText(z1!.cat);
    await expect(target.locator(".pc-loc")).toHaveText(z1!.loc.join(" · "));

    await expect(target.locator("h3.pc-title a")).toHaveAttribute("href", z1!.u!);
    await expect(target.locator("a.pc-company")).toHaveAttribute(
      "href",
      `#/company/${z1!.co}`,
    );
    await expect(target.locator(".pc-head")).toContainText("open");

    await expect(target.locator(".pc-dates")).toContainText("posted");
    await expect(target.locator(".pc-dates")).toContainText("seen");
  });

  test("a closed posting renders its closed_at, not its posted_at", async ({ page }) => {
    await page.goto(`${SERVED}#/catalog?state=closed`);
    await waitForData(page);

    const target = card(page, "Platform Engineer Intern");
    await expect(target.locator(".pc-dates")).toContainText("closed");
    await expect(target.locator(".pc-dates")).not.toContainText("posted");
  });
});
