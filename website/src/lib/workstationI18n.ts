import { getLlmPrivacyLabel, getLlmProviderLabel } from "../features/llm/config";
import type { LlmConfig as UiLlmConfig } from "../features/llm/types";
import {
  BOT_COPY,
  CONFIG_COPY,
  DECISION_TRACE_COPY,
  HISTORY_EXPORT_COPY,
  OCR_PROBE_COPY,
  OCR_SETTINGS_COPY,
  OPERATOR_CONSOLE_COPY,
  POLICY_COMPARE_COPY,
  PRESET_LIBRARY_COPY,
  REPLAY_COPY,
  REPLAY_TIMELINE_COPY,
  RUNTIME_METRICS_COPY,
  RUNTIME_CONTROLS_COPY,
  SESSION_OVERVIEW_COPY,
  WORKSTATION_COPY,
} from "./i18n/workstationCopies";

export type WorkstationLocale = "en" | "fr";

export { WORKSTATION_COPY };


export type WorkstationCopy = (typeof WORKSTATION_COPY)[WorkstationLocale];

export function getWorkstationCopy(locale: WorkstationLocale): WorkstationCopy {
  return WORKSTATION_COPY[locale];
}

export { REPLAY_COPY };

export type ReplayCopy = (typeof REPLAY_COPY)[WorkstationLocale];

export function getReplayCopy(locale: WorkstationLocale): ReplayCopy {
  return REPLAY_COPY[locale];
}

export { CONFIG_COPY };

export type ConfigCopy = (typeof CONFIG_COPY)[WorkstationLocale];

export function getConfigCopy(locale: WorkstationLocale): ConfigCopy {
  return CONFIG_COPY[locale];
}

export { BOT_COPY };

export type BotCopy = (typeof BOT_COPY)[WorkstationLocale];

export function getBotCopy(locale: WorkstationLocale): BotCopy {
  return BOT_COPY[locale];
}

export function getReplayTimelineCopy(locale: WorkstationLocale) {
  return REPLAY_TIMELINE_COPY[locale];
}
export function getSessionOverviewCopy(locale: WorkstationLocale) {
  return SESSION_OVERVIEW_COPY[locale];
}
export function getPolicyCompareCopy(locale: WorkstationLocale) {
  return POLICY_COMPARE_COPY[locale];
}

export function getRuntimeControlsCopy(locale: WorkstationLocale) {
  return RUNTIME_CONTROLS_COPY[locale];
}

export function getHistoryExportCopy(locale: WorkstationLocale) {
  return HISTORY_EXPORT_COPY[locale];
}

export function getRuntimeMetricsCopy(locale: WorkstationLocale) {
  return RUNTIME_METRICS_COPY[locale];
}

export function getDecisionTraceCopy(locale: WorkstationLocale) {
  return DECISION_TRACE_COPY[locale];
}

export function getOperatorConsoleCopy(locale: WorkstationLocale) {
  return OPERATOR_CONSOLE_COPY[locale];
}

export function getPresetLibraryCopy(locale: WorkstationLocale) {
  return PRESET_LIBRARY_COPY[locale];
}

export function getOcrSettingsCopy(locale: WorkstationLocale) {
  return OCR_SETTINGS_COPY[locale];
}

export function getOcrProbeCopy(locale: WorkstationLocale) {
  return OCR_PROBE_COPY[locale];
}

export function useWorkstationText(locale: WorkstationLocale) {
  return {
    locale,
    copy: getWorkstationCopy(locale),
    replayCopy: getReplayCopy(locale),
    configCopy: getConfigCopy(locale),
    botCopy: getBotCopy(locale),
    t: <TResult>(selector: (copy: WorkstationCopy) => TResult) => t(locale, selector),
    localizeProviderModeLabel: (value: string) => localizeProviderModeLabel(value, locale),
    localizePrivacyModeLabel: (value: string) => localizePrivacyModeLabel(value, locale),
    localizeSourceLabel: (value: string | null | undefined) => localizeSourceLabel(value, locale),
    localizeGateReason: (value: string | null | undefined) => localizeGateReason(value, locale),
    localizeHistoryEntryLabel: (value: string) => localizeHistoryEntryLabel(value, locale),
  };
}

export function t<TResult>(locale: WorkstationLocale, selector: (copy: WorkstationCopy) => TResult): TResult {
  return selector(getWorkstationCopy(locale));
}

export function localizeProviderModeLabel(value: string, locale: WorkstationLocale): string {
  if (locale !== "fr") {
    return getLlmProviderLabel(value as UiLlmConfig["providerMode"]);
  }
  return getLlmProviderLabel(value as UiLlmConfig["providerMode"]);
}

export function localizePrivacyModeLabel(value: string, locale: WorkstationLocale): string {
  if (locale !== "fr") {
    return getLlmPrivacyLabel(value as UiLlmConfig["privacyMode"]);
  }
  return getLlmPrivacyLabel(value as UiLlmConfig["privacyMode"]);
}

export function localizeSourceLabel(value: string | null | undefined, locale: WorkstationLocale): string {
  const normalized = (value ?? "").trim().toLowerCase();
  if (!normalized) {
    return locale === "fr" ? "local" : "local";
  }
  if (locale !== "fr") {
    return normalized;
  }
  switch (normalized) {
    case "native":
      return "natif";
    case "http":
      return "http";
    case "fallback":
      return "secours";
    case "legacy":
      return "hérité";
    case "runtime":
      return "exécution locale";
    case "local-json":
      return "json local";
    case "fixture":
      return "jeu d'essai";
    case "operator":
      return "opérateur";
    case "event":
      return "événement";
    case "review":
      return "relecture";
    case "pending":
      return "en attente";
    case "spot":
      return "situation";
    case "general":
      return "général";
    case "balanced":
      return "équilibré";
    case "lab":
      return "labo";
    case "canonical":
      return "canonique";
    default:
      return normalized.replace(/_/g, " ");
  }
}

export function localizeGateReason(value: string | null | undefined, locale: WorkstationLocale): string {
  const normalized = (value ?? "").trim().toLowerCase();
  if (!normalized || locale !== "fr") {
    return value ?? "";
  }
  switch (normalized) {
    case "ready":
      return "prêt";
    case "unsupported_spot":
      return "situation non prise en charge";
    case "fallback_used":
      return "secours utilisé";
    default:
      return normalized.replace(/_/g, " ");
  }
}

export function localizeHistoryEntryLabel(value: string, locale: WorkstationLocale): string {
  if (locale !== "fr") {
    return value;
  }
  return value
    .replace(/\bfallback\b/gi, "secours")
    .replace(/\bruntime\b/gi, "exécution locale")
    .replace(/\breview\b/gi, "relecture")
    .replace(/\bpending\b/gi, "en attente")
    .replace(/\bspot\b/gi, "situation")
    .replace(/\bnative\b/gi, "natif")
    .replace(/\blegacy\b/gi, "hérité");
}
