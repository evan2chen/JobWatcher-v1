import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const trackerRoot = resolve(repoRoot, "tracker");

const MIME: Record<string, string> = {
  ".json": "application/json; charset=utf-8",
  ".jsonl": "text/plain; charset=utf-8",
};

function serveTracker(): Plugin {
  return {
    name: "jobwatcher-serve-tracker",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const path = (req.url || "").split("?")[0];
        if (!path.startsWith("/tracker/")) return next();
        const file = resolve(repoRoot, "." + decodeURIComponent(path));
        if (!file.startsWith(trackerRoot + sep)) return next();
        void stat(file).then(
          (info) => {
            if (!info.isFile()) return next();
            const ext = file.slice(file.lastIndexOf("."));
            res.setHeader("content-type", MIME[ext] || "application/octet-stream");
            createReadStream(file).pipe(res);
          },
          () => next(),
        );
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), serveTracker()],
  base: "./",
  server: {
    proxy: {
      "/api": { target: "http://127.0.0.1:8099", changeOrigin: false },
    },
  },
  build: {
    outDir: "../docs",
    emptyOutDir: false,
    rollupOptions: { output: { manualChunks: undefined } },
  },
});
