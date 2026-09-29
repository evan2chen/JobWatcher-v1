# docs/

Deep documentation for `jobwatcher`, plus the built site.

> **`index.html` and `assets/` in this directory are generated — do not edit them.**
> The site's source is the React app in [`../web/`](../web); `npm run build` there emits
> the bundle here so a checkout or a wheel can serve it with no separate build step.
> The markdown files below and `.nojekyll` are hand-maintained and the build leaves them
> alone.

Start with the root `README.md` and `CONTRIBUTING.md`; come here for depth.

| File | Read it when you need to… |
|------|----------------------------|
| [architecture.md](./architecture.md) | Understand how the engine works, why it's built this way, the diffing strategy and its fallbacks, edge cases, and the verified upstream facts. |
| [data-model.md](./data-model.md) | Look up the exact schema of the store's JSON files, and the schema-version policy. |
| [collectors.md](./collectors.md) | Write a collector for a new job source, or register one. |
| [self-hosting.md](./self-hosting.md) | See how the `jw` CLI, the store, the MCP wrapper, the service and a home directory fit together. |

## Conventions for this directory

- One topic per file; keep the root docs lean and link here for depth.
- When something gets big enough to warrant it, add a subdirectory and link it from this
  index.
- Update the relevant file in the same change that alters behavior — stale docs are worse
  than none.
