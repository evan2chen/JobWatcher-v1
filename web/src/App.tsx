import { useEffect } from "react";
import { ThemeToggle } from "./components/ThemeToggle";
import { CONFIG, DATA_BASE, IS_LOCAL, SOURCE_LABEL } from "./lib/config";
import { useDataState } from "./lib/data";
import { useStore } from "./lib/store";
import { fmtDate } from "./lib/format";
import { Catalog } from "./pages/Catalog";
import { Company } from "./pages/Company";
import { Landing } from "./pages/Landing";
import { catalogHref, useHashRoute } from "./lib/useHashRoute";

function Nav({ route }: { route: string }) {
  const links = [
    { href: "#/", label: "Must apply", key: "landing" },
    { href: catalogHref(), label: "Catalog", key: "catalog" },
  ];
  return (
    <nav className="site-nav">
      {links.map((l) => (
        <a key={l.key} href={l.href} className={route === l.key ? "active" : ""}>
          {l.label}
        </a>
      ))}
    </nav>
  );
}

export function App() {
  const route = useHashRoute();
  const state = useDataState();
  const { sync } = useStore();

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [route.name, route.name === "company" ? route.slug : ""]);

  return (
    <>
      <header className="site-header">
        <div className="wrap">
          <a href="#/" className="brand">
            JobWatcher
          </a>
          <Nav route={route.name} />
          <span className="spacer" />
          <ThemeToggle />
        </div>
      </header>

      <main className="wrap">
        {state.status === "loading" ? (
          <p className="loading">Loading…</p>
        ) : state.status === "error" ? (
          <p className="error">
            Couldn&apos;t load tracker data: {state.message}
            <br />
            <span className="small">
              {IS_LOCAL ? (
                <>
                  Source: local files at {DATA_BASE}tracker/ · serve the repo root (see
                  scripts/serve.ps1) and open /docs/, not docs/index.html directly.
                </>
              ) : (
                <>
                  Source: {CONFIG.owner}/{CONFIG.repo} @ {CONFIG.branch} · tracker data may not
                  be published to this branch yet, and raw.githubusercontent returns 404 for a
                  private repo.
                </>
              )}
            </span>
          </p>
        ) : route.name === "company" ? (
          <Company data={state.data} slug={route.slug} />
        ) : route.name === "catalog" ? (
          <Catalog data={state.data} query={route.query} />
        ) : (
          <Landing data={state.data} />
        )}
      </main>

      <footer className="site-footer">
        <div className="wrap">
          <span>{SOURCE_LABEL}</span>
          <span className={`sync-note small${sync.error ? " is-error" : ""}`}>
            {" · "}
            {sync.error
              ? sync.error
              : sync.mode === "server"
                ? "marks sync to this host"
                : "marks saved in this browser only"}
          </span>
          {state.status === "ready" && state.data.generatedAt ? (
            <span> · generated {fmtDate(state.data.generatedAt)}</span>
          ) : null}
        </div>
      </footer>
    </>
  );
}
