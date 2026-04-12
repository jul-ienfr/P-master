import { Navigate, Route, Routes } from "react-router-dom";
import {
  BotCockpitPage,
  ConfigLabPage,
  ReplayAnalyticsPage,
  SolverStudioPage,
  WorkstationShell,
} from "./WorkstationShell";

function AppRoutes() {
  return (
    <Routes>
      <Route element={<WorkstationShell />}>
        <Route index element={<Navigate to="/solver-studio" replace />} />
        <Route path="/solver-studio" element={<SolverStudioPage />} />
        <Route path="/bot-cockpit" element={<BotCockpitPage />} />
        <Route path="/replay-analytics" element={<ReplayAnalyticsPage />} />
        <Route path="/config-lab" element={<ConfigLabPage />} />
        <Route path="*" element={<Navigate to="/solver-studio" replace />} />
      </Route>
    </Routes>
  );
}

export default AppRoutes;
