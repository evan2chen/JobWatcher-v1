import { rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const docs = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs");

for (const generated of ["assets", "index.html"]) {
  await rm(join(docs, generated), { recursive: true, force: true });
}
