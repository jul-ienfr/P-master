import { describe, expect, it } from "vitest";
import {
  createDefaultJevGateConfig,
  normalizeJevGateConfig,
  toPersistableJevGateConfig,
} from "./jevGateConfig";

describe("jev gate config", () => {
  it("defaults au comportement actuel (single, cloud, observer, fail-open)", () => {
    const defaults = createDefaultJevGateConfig();
    expect(defaults.mode).toBe("observer");
    expect(defaults.deployment).toBe("single");
    expect(defaults.backend).toBe("cloud");
    expect(defaults.baseUrl).toBe("http://127.0.0.1:4000");
    expect(defaults.model).toBe("jev-1.13-free");
    expect(defaults.timeoutS).toBe(0.8);
    expect(defaults.minUpgradeConfidence).toBe(0.3);
    expect(defaults.minDowngradeConfidence).toBe(0.6);
    expect(defaults.riskyThreshold).toBe(0.7);
    expect(defaults.lan.model).toBe("qwen2.5-vl-3b");
    expect(defaults.lan.apiKeyEnv).toBe("POKER_JEV_LAN_KEY");
    expect(defaults.multimodal.enabled).toBe(false);
    expect(defaults.multimodal.mode).toBe("text_only");
  });

  it("tolère le snake_case et normalise les valeurs invalides", () => {
    const normalized = normalizeJevGateConfig({
      mode: "ENFORCING",
      deployment: "DUAL",
      backend: "local",
      min_upgrade_confidence: 2,
      min_downgrade_confidence: -1,
      lan: {
        base_url: "http://192.168.1.50:30000",
        timeout_text_s: 0,
        api_key_env: "",
      },
      multimodal: { enabled: true, mode: "crops_offline", max_images: 50 },
      usages: { judge: { enabled: false, timeout_s: 0 } },
    });

    expect(normalized.mode).toBe("enforcing");
    expect(normalized.deployment).toBe("dual");
    expect(normalized.backend).toBe("local");
    expect(normalized.minUpgradeConfidence).toBe(1);
    expect(normalized.minDowngradeConfidence).toBe(0);
    expect(normalized.lan.baseUrl).toBe("http://192.168.1.50:30000");
    expect(normalized.lan.timeoutTextS).toBe(1.0);
    expect(normalized.lan.apiKeyEnv).toBe("POKER_JEV_LAN_KEY");
    expect(normalized.multimodal.enabled).toBe(true);
    expect(normalized.multimodal.maxImages).toBe(8);
    expect(normalized.usages.judge.enabled).toBe(false);
    expect(normalized.usages.judge.timeoutS).toBe(15);
  });

  it("verrouille crops_live sur text_only et replie dual sans URL sur single", () => {
    const normalized = normalizeJevGateConfig({
      deployment: "dual",
      multimodal: { enabled: true, mode: "crops_live" },
    });

    expect(normalized.multimodal.mode).toBe("text_only");
    expect(normalized.multimodal.enabled).toBe(false);
    expect(normalized.deployment).toBe("single");
  });

  it("sérialise en snake_case sans valeur de clé", () => {
    const persistable = toPersistableJevGateConfig(createDefaultJevGateConfig());
    expect(persistable.base_url).toBe("http://127.0.0.1:4000");
    expect(persistable.min_upgrade_confidence).toBe(0.3);
    const lan = persistable.lan as Record<string, unknown>;
    expect(lan.api_key_env).toBe("POKER_JEV_LAN_KEY");
    expect("api_key" in lan).toBe(false);
    expect(JSON.stringify(persistable)).not.toContain("POKER_JEV_LAN_KEY_VALUE");
  });

  it("sérialise un round-trip snake_case sans perte des seuils", () => {
    const before = normalizeJevGateConfig({
      min_upgrade_confidence: 0.45,
      lan: { base_url: "http://192.168.1.50:30000" },
      multimodal: { mode: "crops_offline", enabled: true },
    });
    const after = normalizeJevGateConfig(toPersistableJevGateConfig(before));
    expect(after.minUpgradeConfidence).toBe(0.45);
    expect(after.lan.baseUrl).toBe("http://192.168.1.50:30000");
    expect(after.multimodal.mode).toBe("crops_offline");
    expect(after.multimodal.enabled).toBe(true);
  });
});
