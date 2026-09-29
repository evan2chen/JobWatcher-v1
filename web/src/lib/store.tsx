import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import * as api from "./api";
import { useLocalStorage, readLocalStorage, writeLocalStorage } from "./useLocalStorage";
import { PRESET_PROFILES, type Profile } from "./profiles";

export type StatusValue =
  | "interested"
  | "applied"
  | "interviewing"
  | "rejected"
  | "offer"
  | "skipped"
  | "closed";
export type StatusEntry = { status: StatusValue; at: number };
export type StatusMap = Record<string, StatusEntry>;

export type SyncMode = "local" | "server";

const K_OVERRIDES = "jw-profile-overrides";
const K_ACTIVE = "jw-active-profile";
const K_STATUS = "jw-status";
const K_LAST_VISIT = "jw-last-visit";
const K_ADOPTED = "jw-adopted";

const ACTIVE_SETTING = "active_profile";

type Store = {
  profiles: Profile[];
  activeProfile: Profile;
  setActiveProfileId: (id: string) => void;
  updateProfile: (next: Profile) => void;
  resetProfile: (id: string) => void;
  isCustomized: (id: string) => boolean;

  status: StatusMap;
  setStatus: (postingId: string, value: StatusValue | null) => void;
  clearAllStatus: () => void;

  lastVisit: number;

  sync: { mode: SyncMode; error: string | null };
};

const StoreContext = createContext<Store | null>(null);

function toStatusMap(records: api.ApplicationRecord[]): StatusMap {
  const map: StatusMap = {};
  for (const r of records) {
    if (!r.posting_id) continue;
    map[r.posting_id] = { status: r.status, at: r.status_at };
  }
  return map;
}

export function StoreProvider({ children }: { children: ReactNode }) {
  const [overrides, setOverrides] = useLocalStorage<Record<string, Profile>>(K_OVERRIDES, {});
  const [activeId, setActiveId] = useLocalStorage<string>(K_ACTIVE, PRESET_PROFILES[0].id);
  const [status, setStatusMap] = useLocalStorage<StatusMap>(K_STATUS, {});
  const [, setLastVisit] = useLocalStorage<number>(K_LAST_VISIT, 0);

  const [mode, setMode] = useState<SyncMode>("local");
  const [error, setError] = useState<string | null>(null);

  const lastVisitRef = useRef<number | null>(null);
  if (lastVisitRef.current === null) {
    lastVisitRef.current = Number(readLocalStorage<number>(K_LAST_VISIT, 0)) || 0;
    setLastVisit(Math.floor(Date.now() / 1000));
  }

  const adopted = useRef(false);
  useEffect(() => {
    if (adopted.current) return;
    adopted.current = true;
    let cancelled = false;

    (async () => {
      if (!(await api.probe())) return;
      try {
        let records = await api.getApplications();

        const local = readLocalStorage<StatusMap>(K_STATUS, {});
        const alreadyAdopted = readLocalStorage<boolean>(K_ADOPTED, false);
        if (!alreadyAdopted && records.length === 0 && Object.keys(local).length > 0) {
          for (const [postingId, entry] of Object.entries(local)) {
            try {
              await api.setStatus(postingId, entry.status);
            } catch {}
          }
          records = await api.getApplications();
        }
        writeLocalStorage(K_ADOPTED, true);

        const profiles = await api.getProfiles();
        if (cancelled) return;

        setStatusMap(toStatusMap(records));
        setOverrides(profiles.overrides);
        const serverActive = profiles.settings?.[ACTIVE_SETTING];
        if (typeof serverActive === "string") setActiveId(serverActive);
        setMode("server");
        setError(null);
      } catch (err) {
        if (!cancelled) setError(`could not load from the server: ${String(err)}`);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [setStatusMap, setOverrides, setActiveId]);

  const push = useCallback(
    (send: () => Promise<unknown>, rollback: () => void, what: string) => {
      if (mode !== "server") return;
      send()
        .then(() => setError(null))
        .catch((err) => {
          rollback();
          setError(`${what} did not save: ${String(err)}`);
        });
    },
    [mode],
  );

  const value = useMemo<Store>(() => {
    const profiles = PRESET_PROFILES.map((p) => overrides[p.id] ?? p);
    const activeProfile = profiles.find((p) => p.id === activeId) ?? profiles[0];

    return {
      profiles,
      activeProfile,

      setActiveProfileId: (id) => {
        const previous = activeId;
        setActiveId(id);
        push(() => api.setSetting(ACTIVE_SETTING, id), () => setActiveId(previous),
             "profile choice");
      },

      updateProfile: (next) => {
        const previous = overrides;
        setOverrides((prev) => ({ ...prev, [next.id]: next }));
        push(() => api.saveProfile(next.id, next), () => setOverrides(previous),
             "profile");
      },

      resetProfile: (id) => {
        const previous = overrides;
        setOverrides((prev) => {
          const { [id]: _dropped, ...rest } = prev;
          return rest;
        });
        push(() => api.deleteProfile(id), () => setOverrides(previous), "profile reset");
      },

      isCustomized: (id) => id in overrides,

      status,
      setStatus: (postingId, val) => {
        const previous = status;
        setStatusMap((prev) => {
          if (val === null) {
            const { [postingId]: _dropped, ...rest } = prev;
            return rest;
          }
          return { ...prev, [postingId]: { status: val, at: Math.floor(Date.now() / 1000) } };
        });
        push(
          () => (val === null ? api.clearStatus(postingId) : api.setStatus(postingId, val)),
          () => setStatusMap(previous),
          "status",
        );
      },

      clearAllStatus: () => {
        const previous = status;
        setStatusMap({});
        push(
          () => Promise.all(Object.keys(previous).map((id) => api.clearStatus(id))),
          () => setStatusMap(previous),
          "clearing marks",
        );
      },

      lastVisit: lastVisitRef.current ?? 0,
      sync: { mode, error },
    };
  }, [overrides, activeId, status, mode, error, setOverrides, setActiveId, setStatusMap, push]);

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore(): Store {
  const ctx = useContext(StoreContext);
  if (!ctx) throw new Error("useStore must be used inside <StoreProvider>");
  return ctx;
}
