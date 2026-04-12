import { createContext, useContext } from "react";
import { alpha, createTheme } from "@mui/material/styles";

export type WorkstationThemeMode = "light" | "dark";

export const WORKSTATION_THEME_STORAGE_KEY = "pokermaster:v2:theme-mode";

type WorkstationThemeModeContextValue = {
  mode: WorkstationThemeMode;
  setMode: (mode: WorkstationThemeMode) => void;
};

export const WorkstationThemeModeContext = createContext<WorkstationThemeModeContextValue | null>(
  null
);

export function useWorkstationThemeMode() {
  const value = useContext(WorkstationThemeModeContext);
  if (!value) {
    throw new Error("Workstation theme mode context is not available");
  }
  return value;
}

export function resolveInitialThemeMode(): WorkstationThemeMode {
  if (typeof window === "undefined") {
    return "light";
  }

  const stored = window.localStorage.getItem(WORKSTATION_THEME_STORAGE_KEY);
  if (stored === "light" || stored === "dark") {
    return stored;
  }

  if (window.matchMedia?.("(prefers-color-scheme: dark)").matches) {
    return "dark";
  }

  return "light";
}

export function createWorkstationTheme(mode: WorkstationThemeMode) {
  const isDark = mode === "dark";

  const palette = {
    mode,
    primary: {
      main: isDark ? "#ffb55c" : "#c47a16",
      contrastText: isDark ? "#181107" : "#ffffff",
    },
    secondary: {
      main: isDark ? "#61d3d4" : "#0f8f92",
    },
    success: {
      main: isDark ? "#59c173" : "#18804b",
    },
    warning: {
      main: isDark ? "#f5a623" : "#b96a00",
    },
    error: {
      main: isDark ? "#ff6b6b" : "#c53434",
    },
    background: {
      default: isDark ? "#071018" : "#f3f5f8",
      paper: isDark ? "#0d1722" : "#ffffff",
    },
    text: {
      primary: isDark ? "#e8eef7" : "#101828",
      secondary: isDark ? "#97a7be" : "#526173",
    },
    divider: isDark ? "rgba(215, 224, 239, 0.12)" : "rgba(16, 24, 40, 0.08)",
  } as const;

  return createTheme({
    palette,
    shape: {
      borderRadius: 18,
    },
    typography: {
      fontFamily: '"Trebuchet MS", "Avenir Next", "Segoe UI", sans-serif',
      h5: {
        fontWeight: 700,
        letterSpacing: "-0.03em",
      },
      h6: {
        fontWeight: 700,
        letterSpacing: "-0.02em",
      },
      button: {
        textTransform: "none",
        fontWeight: 700,
      },
    },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          body: {
            backgroundColor: palette.background.default,
            color: palette.text.primary,
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            backgroundImage: "none",
            border: `1px solid ${alpha(palette.text.primary, isDark ? 0.12 : 0.08)}`,
            boxShadow: isDark
              ? "0 20px 52px rgba(0, 0, 0, 0.28)"
              : "0 18px 48px rgba(15, 23, 42, 0.08)",
          },
        },
      },
      MuiCard: {
        styleOverrides: {
          root: {
            backgroundColor: palette.background.paper,
            backgroundImage: "none",
          },
        },
      },
      MuiOutlinedInput: {
        styleOverrides: {
          root: {
            backgroundColor: alpha(palette.text.primary, isDark ? 0.05 : 0.02),
          },
        },
      },
      MuiToggleButton: {
        styleOverrides: {
          root: {
            textTransform: "none",
          },
        },
      },
    },
  });
}
