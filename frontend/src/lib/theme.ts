import { useCallback, useState } from "react";

export type Theme = "light" | "dark" | "system";

function apply(theme: Theme): void {
  const dark =
    theme === "dark" ||
    (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

function read(): Theme {
  try {
    const saved = localStorage.getItem("theme");
    return saved === "light" || saved === "dark" ? saved : "system";
  } catch {
    return "system";
  }
}

export function useTheme(): [Theme, (theme: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(read);
  const setTheme = useCallback((next: Theme) => {
    try {
      if (next === "system") localStorage.removeItem("theme");
      else localStorage.setItem("theme", next);
    } catch {
      // Storage unavailable (private mode): the choice simply isn't remembered.
    }
    apply(next);
    setThemeState(next);
  }, []);
  return [theme, setTheme];
}
