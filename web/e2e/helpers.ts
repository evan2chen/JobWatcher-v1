import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, type Page } from "@playwright/test";

import { FIXTURE, API_BASE_URL, STATIC_BASE_URL } from "./playwright.config";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

export const SERVED = `${API_BASE_URL}/`;
export const STATIC = `${STATIC_BASE_URL}/docs/index.html`;

export function jw(...args: string[]): any {
  const out = execFileSync("python", ["-m", "jw", "--db", FIXTURE.db, "--format", "json", ...args], {
    cwd: repoRoot,
    encoding: "utf-8",
  });
  return JSON.parse(out);
}

export function applicationsInStore(): Array<{ posting_id: string; status: string }> {
  return jw("applications", "list", "--full", "--limit", "0").applications ?? [];
}

const RESET = `
import sys
from jw import db
con = db.connect(sys.argv[1])
con.execute("DELETE FROM applications")
con.execute("DELETE FROM profiles")
con.execute("DELETE FROM settings")
con.commit()
`;

export function resetStore(): void {
  execFileSync("python", ["-c", RESET, FIXTURE.db], { cwd: repoRoot });
}

export async function waitForData(page: Page): Promise<void> {
  await expect(page.locator("p.loading")).toHaveCount(0, { timeout: 15_000 });
  await expect(page.locator("main h1")).toBeVisible();
}

export async function gotoLanding(page: Page, base: string): Promise<void> {
  await page.goto(base);
  await waitForData(page);
}

export async function seedLocalStorage(
  page: Page,
  entries: Record<string, unknown>,
): Promise<void> {
  await page.addInitScript((pairs) => {
    if (window.localStorage.getItem("jw-e2e-seeded")) return;
    window.localStorage.setItem("jw-e2e-seeded", "1");
    for (const [k, v] of Object.entries(pairs)) {
      window.localStorage.setItem(k, JSON.stringify(v));
    }
  }, entries);
}

export function card(page: Page, title: string) {
  return page.locator("article.posting-card").filter({ hasText: title });
}

export const cards = (page: Page) => page.locator("article.posting-card");

export function facetGroup(page: Page, legend: string) {
  return page.locator("fieldset.facet-group").filter({
    has: page.locator("legend", { hasText: new RegExp(`^${legend}$`) }),
  });
}

export const syncNote = (page: Page) => page.locator(".sync-note");
