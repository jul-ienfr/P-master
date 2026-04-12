import { useEffect, useMemo, useState } from "react";
import { CssBaseline, ThemeProvider } from "@mui/material";
import { HashRouter } from "react-router-dom";
import {
  WorkstationThemeModeContext,
  WORKSTATION_THEME_STORAGE_KEY,
  createWorkstationTheme,
  resolveInitialThemeMode,
} from "./lib/theme";
import { AppErrorBoundary } from "./components/AppErrorBoundary";
import AppRoutes from "./routes/Routing";
import "./App.css";

function App() {
  const [themeMode, setThemeMode] = useState(resolveInitialThemeMode);
  const theme = useMemo(() => createWorkstationTheme(themeMode), [themeMode]);

  useEffect(() => {
    if (typeof document !== "undefined") {
      document.documentElement.dataset.theme = themeMode;
    }
    if (typeof window !== "undefined") {
      window.localStorage.setItem(WORKSTATION_THEME_STORAGE_KEY, themeMode);
    }
  }, [themeMode]);

  return (
    <AppErrorBoundary>
      <ThemeProvider theme={theme}>
        <CssBaseline enableColorScheme />
        <WorkstationThemeModeContext.Provider value={{ mode: themeMode, setMode: setThemeMode }}>
          <HashRouter>
            <AppRoutes />
          </HashRouter>
        </WorkstationThemeModeContext.Provider>
      </ThemeProvider>
    </AppErrorBoundary>
  );
}

export default App;
