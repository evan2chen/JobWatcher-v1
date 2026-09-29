const params = new URLSearchParams(location.search);

export const CONFIG = {
  owner: params.get("owner") || "evan2chen",
  repo: params.get("repo") || "JobWatcher",
  branch: params.get("branch") || "local",
};

export const IS_LOCAL = CONFIG.branch === "local";

export const DATA_BASE = params.get("data") || "../";

export function RAW(path: string): string {
  if (IS_LOCAL) return `${DATA_BASE}${path}`;
  return `https://raw.githubusercontent.com/${CONFIG.owner}/${CONFIG.repo}/${CONFIG.branch}/${path}`;
}

export const API_BASE = params.get("api") || "./api";

export const SOURCE_LABEL = IS_LOCAL
  ? `data: local · ${DATA_BASE}tracker`
  : `data: ${CONFIG.owner}/${CONFIG.repo} @ ${CONFIG.branch}`;
