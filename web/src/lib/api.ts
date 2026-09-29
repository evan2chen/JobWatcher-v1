import { API_BASE } from "./config";
import type { Profile } from "./profiles";

export type ServerStatus =
  | "interested"
  | "applied"
  | "interviewing"
  | "rejected"
  | "offer"
  | "skipped"
  | "closed";

export type ApplicationRecord = {
  posting_id: string | null;
  listing_id: string | null;
  company_id: string | null;
  status: ServerStatus;
  status_at: number;
  notes: string;
};

type ProfilesPayload = {
  overrides: Record<string, Profile>;
  settings: Record<string, unknown>;
};

const url = (path: string) => `${API_BASE}${path}`;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url(path), {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { error?: string };
      if (body?.error) detail = body.error;
    } catch {}
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export async function probe(): Promise<boolean> {
  try {
    const res = await fetch(url("/health"), { method: "GET" });
    if (!res.ok) return false;
    const body = (await res.json()) as { ok?: boolean; writes?: boolean };
    return Boolean(body?.ok && body?.writes);
  } catch {
    return false;
  }
}

export async function getApplications(): Promise<ApplicationRecord[]> {
  const body = await request<{ applications: ApplicationRecord[] }>("/applications");
  return body.applications ?? [];
}

export async function setStatus(postingId: string, status: ServerStatus, note?: string) {
  return request<{ application: ApplicationRecord }>(`/applications/${encodeURIComponent(postingId)}`, {
    method: "PUT",
    body: JSON.stringify(note ? { status, note } : { status }),
  });
}

export async function clearStatus(postingId: string) {
  try {
    await request(`/applications/${encodeURIComponent(postingId)}`, { method: "DELETE" });
  } catch (err) {
    if (!String(err).includes("404")) throw err;
  }
}

export async function getProfiles(): Promise<ProfilesPayload> {
  const body = await request<ProfilesPayload>("/profiles");
  return { overrides: body.overrides ?? {}, settings: body.settings ?? {} };
}

export async function saveProfile(id: string, profile: Profile) {
  return request(`/profiles/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify({ profile }),
  });
}

export async function deleteProfile(id: string) {
  return request(`/profiles/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function setSetting(key: string, value: unknown) {
  return request(`/settings/${encodeURIComponent(key)}`, {
    method: "PUT",
    body: JSON.stringify({ value }),
  });
}
