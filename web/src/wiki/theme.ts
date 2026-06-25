// Theme state, shared by the chrome (toggle) and any component that must
// re-render when the palette flips — notably <Mermaid>, whose SVG colours are
// baked in at render time and cannot ride CSS variables.
//
// The <html data-theme> attribute is the single source of truth. It is set
// before first paint by the inline boot script in index.html (so there is no
// flash), and mutated here. Listeners subscribe to a window CustomEvent.

import { useEffect, useState } from "react";

export type ThemeName = "light" | "dark";

const STORAGE_KEY = "pyverdex-theme";
const CHANGE_EVENT = "pyverdex:themechange";

export function getTheme(): ThemeName {
  if (typeof document === "undefined") return "light";
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

export function setTheme(theme: ThemeName): void {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* private mode / disabled storage — the attribute still applies for this session */
  }
  window.dispatchEvent(new CustomEvent(CHANGE_EVENT, { detail: theme }));
}

export function toggleTheme(): ThemeName {
  const next: ThemeName = getTheme() === "dark" ? "light" : "dark";
  setTheme(next);
  return next;
}

// Subscribe a component to the current theme. Re-renders on toggle.
export function useTheme(): ThemeName {
  const [theme, setThemeState] = useState<ThemeName>(getTheme);
  useEffect(() => {
    const onChange = () => setThemeState(getTheme());
    window.addEventListener(CHANGE_EVENT, onChange);
    return () => window.removeEventListener(CHANGE_EVENT, onChange);
  }, []);
  return theme;
}
