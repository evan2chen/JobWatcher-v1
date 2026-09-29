import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..", "..");

export const API_PORT = 41711;
export const STATIC_PORT = 41712;
export const API_BASE_URL = `http://127.0.0.1:${API_PORT}`;
export const STATIC_BASE_URL = `http://127.0.0.1:${STATIC_PORT}`;

const fixtureDir = join(here, ".fixture");
mkdirSync(fixtureDir, { recursive: true });

export const FIXTURE = JSON.parse(
  execFileSync("python", [join(repoRoot, "tests", "fixture.py"), fixtureDir], {
    cwd: repoRoot,
    encoding: "utf-8",
  }),
) as { root: string; db: string; site: string; now: number };

export default defineConfig({
  testDir: here,
  outputDir: join(fixtureDir, "results"),
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [["list"], ["github"]] : [["list"]],
  use: {
    ...devices["Desktop Chrome"],
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: [
        "python", "-m", "jw",
        "--db", `"${FIXTURE.db}"`,
        "serve",
        "--root", `"${FIXTURE.root}"`,
        "--bind", "127.0.0.1",
        "--port", String(API_PORT),
      ].join(" "),
      cwd: repoRoot,
      url: `${API_BASE_URL}/api/health`,
      reuseExistingServer: false,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: `python -m http.server ${STATIC_PORT} --bind 127.0.0.1 --directory "${FIXTURE.root}"`,
      cwd: repoRoot,
      url: `${STATIC_BASE_URL}/docs/index.html`,
      reuseExistingServer: false,
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});
