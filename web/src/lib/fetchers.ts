import { RAW } from "./config";

export async function fetchJSON<T>(path: string): Promise<T> {
  const res = await fetch(RAW(path));
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
  return (await res.json()) as T;
}

export async function fetchJSONL<T>(path: string): Promise<T[]> {
  const res = await fetch(RAW(path));
  if (!res.ok) {
    if (res.status === 404) return [];
    throw new Error(`${path} → HTTP ${res.status}`);
  }
  const text = await res.text();
  if (!text) return [];
  const out: T[] = [];
  for (const line of text.split("\n")) {
    if (!line) continue;
    try {
      out.push(JSON.parse(line) as T);
    } catch {}
  }
  return out;
}
