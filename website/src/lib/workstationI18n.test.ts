import { describe, expect, it } from "vitest";
import {
  getBotCopy,
  getConfigCopy,
  getDecisionTraceCopy,
  getHistoryExportCopy,
  getOcrProbeCopy,
  getOcrSettingsCopy,
  getOperatorConsoleCopy,
  getPolicyCompareCopy,
  getPresetLibraryCopy,
  getReplayCopy,
  getReplayTimelineCopy,
  getRuntimeControlsCopy,
  getRuntimeMetricsCopy,
  getSessionOverviewCopy,
  getWorkstationCopy,
  localizeGateReason,
  localizeHistoryEntryLabel,
  localizeSourceLabel,
  t,
} from "./workstationI18n";

describe("workstation i18n copies", () => {
  it("returns french workstation copy entries", () => {
    const copy = getWorkstationCopy("fr");
    expect(copy.solverStudio.title.length).toBeGreaterThan(0);
    expect(copy.assistant.title).toBe("Assistant optionnel");
  });

  it("returns english replay/config/bot copy entries", () => {
    expect(getReplayCopy("en").status).toBe("Status");
    expect(getConfigCopy("en").refreshButton).toBe("Refresh");
    expect(getBotCopy("en").traceTitle.length).toBeGreaterThan(0);
  });

  it("supports typed selector access with t()", () => {
    expect(t("fr", (copy) => copy.common.loading)).toBe("Chargement");
    expect(t("en", (copy) => copy.language.label)).toBe("Language");
  });

  it("returns replay secondary copies", () => {
    expect(getReplayTimelineCopy("fr").reviewTitle.length).toBeGreaterThan(0);
    expect(getSessionOverviewCopy("en").timelineReady).toBe("Timeline ready");
    expect(getPolicyCompareCopy("fr").title.length).toBeGreaterThan(0);
  });

  it("returns config secondary copies", () => {
    expect(getRuntimeControlsCopy("fr").title.length).toBeGreaterThan(0);
    expect(getPresetLibraryCopy("en").newPreset).toBe("New preset");
    expect(getOcrSettingsCopy("fr").title.length).toBeGreaterThan(0);
    expect(getOcrProbeCopy("en").run).toBe("Run OCR probe");
  });

  it("returns bot secondary copies", () => {
    expect(getHistoryExportCopy("fr").title.length).toBeGreaterThan(0);
    expect(getRuntimeMetricsCopy("en").title.length).toBeGreaterThan(0);
    expect(getDecisionTraceCopy("fr").traceDetailsTitle).toBe("Détails de trace");
    expect(getOperatorConsoleCopy("en").defaultTitle.length).toBeGreaterThan(0);
  });
});

describe("workstation i18n helpers", () => {
  it("localizes common source labels in french", () => {
    expect(localizeSourceLabel("native", "fr")).toBe("natif");
    expect(localizeSourceLabel("runtime", "fr")).toBe("exécution locale");
    expect(localizeSourceLabel("fallback", "fr")).toBe("secours");
  });

  it("keeps english source labels normalized", () => {
    expect(localizeSourceLabel("native", "en")).toBe("native");
    expect(localizeSourceLabel("fallback", "en")).toBe("fallback");
  });

  it("localizes gate reasons in french", () => {
    expect(localizeGateReason("ready", "fr")).toBe("prêt");
    expect(localizeGateReason("unsupported_spot", "fr")).toBe("situation non prise en charge");
    expect(localizeGateReason("fallback_used", "fr")).toBe("secours utilisé");
  });

  it("localizes history entry labels in french", () => {
    expect(localizeHistoryEntryLabel("fallback runtime review pending native legacy spot", "fr")).toBe(
      "secours exécution locale relecture en attente natif hérité situation",
    );
  });
});
