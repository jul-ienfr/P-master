import type {
  BotCockpitAlertItem,
  BotCockpitAlertSeverity,
  BotCockpitAlertSummary,
  BotCockpitOperatorMode,
  BotCockpitRuntimeState,
  BotCockpitTone,
} from "./types";

function tone(label: string, color: BotCockpitTone["color"], description: string): BotCockpitTone {
  return { label, color, description };
}

export function getBotCockpitRuntimeTone(state: BotCockpitRuntimeState): BotCockpitTone {
  switch (state) {
    case "ready":
      return tone("Ready", "success", "The runtime is healthy and the cockpit can trust fresh data.");
    case "streaming":
      return tone("Streaming", "secondary", "Live updates are flowing from the local runtime.");
    case "degraded":
      return tone("Degraded", "warning", "The cockpit is usable, but one or more signals need attention.");
    case "offline":
      return tone("Offline", "error", "The cockpit is disconnected and should fall back safely.");
    case "error":
      return tone("Error", "error", "The runtime has failed and needs operator attention.");
    case "idle":
    default:
      return tone("Idle", "default", "The cockpit is idle and waiting for a live snapshot.");
  }
}

export function getBotCockpitOperatorTone(mode: BotCockpitOperatorMode): BotCockpitTone {
  switch (mode) {
    case "assist":
      return tone("Assist", "primary", "The operator can review guidance while staying in control.");
    case "shadow":
      return tone("Shadow", "secondary", "The cockpit observes and compares without taking over.");
    case "manual_override":
      return tone("Manual override", "warning", "The operator can override suggestions at any time.");
    case "diagnostic":
      return tone("Diagnostic", "secondary", "The cockpit exposes more telemetry for troubleshooting.");
    case "observe_only":
    default:
      return tone("Observe only", "default", "The cockpit keeps watch without adding pressure.");
  }
}

export function getBotCockpitAlertTone(severity: BotCockpitAlertSeverity): BotCockpitTone {
  switch (severity) {
    case "success":
      return tone("Success", "success", "The signal is positive and does not need action.");
    case "warning":
      return tone("Warning", "warning", "The signal deserves attention, but the cockpit can continue.");
    case "error":
      return tone("Error", "error", "The signal is urgent and should be reviewed immediately.");
    case "info":
    default:
      return tone("Info", "primary", "The signal is informative and useful for context.");
  }
}

export function summarizeBotCockpitAlerts(
  alerts: BotCockpitAlertItem[]
): BotCockpitAlertSummary {
  const summary: BotCockpitAlertSummary = {
    total: alerts.length,
    open: 0,
    acknowledged: 0,
    info: 0,
    success: 0,
    warning: 0,
    error: 0,
    dominantSeverity: "none",
  };

  for (const alert of alerts) {
    if (alert.acknowledged) {
      summary.acknowledged += 1;
    } else {
      summary.open += 1;
    }

    summary[alert.severity] += 1;
  }

  if (summary.error > 0) {
    summary.dominantSeverity = "error";
  } else if (summary.warning > 0) {
    summary.dominantSeverity = "warning";
  } else if (summary.info > 0) {
    summary.dominantSeverity = "info";
  } else if (summary.success > 0) {
    summary.dominantSeverity = "success";
  }

  return summary;
}

export function isBotCockpitRuntimeHealthy(state: BotCockpitRuntimeState): boolean {
  return state === "ready" || state === "streaming";
}

export function isBotCockpitRuntimeOffline(state: BotCockpitRuntimeState): boolean {
  return state === "offline";
}

export function createBotCockpitSummary(
  status: BotCockpitRuntimeState,
  operatorMode: BotCockpitOperatorMode,
  alertSummary: BotCockpitAlertSummary
): string {
  const runtimeLabel = getBotCockpitRuntimeTone(status).label.toLowerCase();
  const operatorLabel = getBotCockpitOperatorTone(operatorMode).label.toLowerCase();
  const alertLabel =
    alertSummary.open > 0
      ? `${alertSummary.open} open alert${alertSummary.open === 1 ? "" : "s"}`
      : "no open alerts";

  return `${runtimeLabel}, ${operatorLabel}, ${alertLabel}.`;
}

export function normalizeAlertSeverity(
  value: string | null | undefined
): BotCockpitAlertSeverity {
  switch (value) {
    case "success":
    case "warning":
    case "error":
      return value;
    case "info":
    default:
      return "info";
  }
}

