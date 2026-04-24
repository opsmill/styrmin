import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
} from "react";
import type { ReactNode } from "react";

type Theme = "light" | "dark";

interface ThemeContextValue {
  theme: Theme;
  toggleTheme: () => void;
}

const STORAGE_KEY = "styrmin-theme";
const COLOR_SCHEME_QUERY = "(prefers-color-scheme: dark)";

const ThemeContext = createContext<ThemeContextValue | null>(null);

function getStoredTheme(): Theme | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "dark" || stored === "light") return stored;
  } catch {
    // localStorage may not be available in tests
  }
  return null;
}

function getSystemTheme(): Theme {
  if (typeof window === "undefined" || !window.matchMedia) return "light";
  return window.matchMedia(COLOR_SCHEME_QUERY).matches ? "dark" : "light";
}

function getInitialTheme(): Theme {
  return getStoredTheme() ?? getSystemTheme();
}

function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle("dark", theme === "dark");
}

export function createThemeProvider() {
  function ThemeProvider({ children }: { children: ReactNode }) {
    const [theme, setTheme] = useState<Theme>(getInitialTheme);
    const [hasManualChoice, setHasManualChoice] = useState<boolean>(
      () => getStoredTheme() !== null,
    );

    useEffect(() => {
      applyTheme(theme);
    }, [theme]);

    useEffect(() => {
      if (hasManualChoice) return;
      if (typeof window === "undefined" || !window.matchMedia) return;
      const mq = window.matchMedia(COLOR_SCHEME_QUERY);
      const handler = (event: MediaQueryListEvent) => {
        setTheme(event.matches ? "dark" : "light");
      };
      mq.addEventListener("change", handler);
      return () => mq.removeEventListener("change", handler);
    }, [hasManualChoice]);

    const toggleTheme = useCallback(() => {
      setTheme((prev) => {
        const next = prev === "light" ? "dark" : "light";
        try {
          localStorage.setItem(STORAGE_KEY, next);
        } catch {
          // localStorage may not be available in tests
        }
        return next;
      });
      setHasManualChoice(true);
    }, []);

    return (
      <ThemeContext value={{ theme, toggleTheme }}>{children}</ThemeContext>
    );
  }

  return ThemeProvider;
}

export const ThemeProvider = createThemeProvider();

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return context;
}
