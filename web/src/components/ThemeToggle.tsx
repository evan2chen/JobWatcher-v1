import { useState } from "react";

type Theme = "light" | "dark" | null;

function current(): Theme {
  return (document.documentElement.getAttribute("data-theme") as Theme) ?? null;
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(current);

  const toggle = () => {
    const next: Theme =
      theme === "dark"
        ? "light"
        : theme === "light"
          ? "dark"
          : matchMedia("(prefers-color-scheme: dark)").matches
            ? "light"
            : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem("jw-theme", next);
    } catch {}
    setTheme(next);
  };

  return (
    <button
      type="button"
      className="ghost-btn"
      onClick={toggle}
      title="Toggle theme"
      aria-label="Toggle light/dark theme"
    >
      ◐
    </button>
  );
}
