import type { WorkstationLocale } from "../workstationI18n";

export { WORKSTATION_COPY } from "./core.copy";
export {
  BOT_COPY,
  DECISION_TRACE_COPY,
  HISTORY_EXPORT_COPY,
  OPERATOR_CONSOLE_COPY,
  RUNTIME_METRICS_COPY,
} from "./bot.copy";
export {
  CONFIG_COPY,
  OCR_PROBE_COPY,
  OCR_SETTINGS_COPY,
  PRESET_LIBRARY_COPY,
  RUNTIME_CONTROLS_COPY,
} from "./config.copy";
export {
  POLICY_COMPARE_COPY,
  REPLAY_COPY,
  REPLAY_TIMELINE_COPY,
  SESSION_OVERVIEW_COPY,
} from "./replay.copy";



export function pickByLocale<T>(map: Record<WorkstationLocale, T>, locale: WorkstationLocale): T {
  return map[locale];
}
