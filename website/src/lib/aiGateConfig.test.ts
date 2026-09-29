import { describe, expect, it } from "vitest";
import {
  applyAiGatePreset,
  createDefaultAiGateConfig,
  isLoopbackUrl,
  normalizeAiGateConfig,
  toPersistableAiGateConfig,
} from "./aiGateConfig";

describe("ai gate config", () => {
  it("défauts verrouillés LAN/offline strict : routeur jev, zéro WAN, jamais de valeur de clé", () => {
    const defaults = createDefaultAiGateConfig();
    expect(defaults.provider).toBe("jev");
    expect(defaults.offlineMode).toBe(true);
    expect(defaults.cloudFallback).toBe(false);
    expect(defaults.djev.baseUrl).toBe("http://127.0.0.1:4000");
    expect(defaults.djev.cloudUrl).toBe("https://api.typesafe.ai/v1/systemone");
    expect(defaults.djev.lanUrl).toBe("http://127.0.0.1:4000");
    expect(defaults.djev.model).toBe("jev-1.13.0");
    expect(defaults.djev.apiKeyEnv).toBe("TYPESAFE_API_KEY");
    expect(defaults.djev.timeoutS).toBe(5.0);
    expect(defaults.djev.mode).toBe("observer");
    expect(defaults.djev.offlineMode).toBe(true);
    expect(isLoopbackUrl(defaults.djev.baseUrl)).toBe(true);
    expect(defaults.jev.model).toBe("jev-1.13-free");
  });

  it("valide contre docs/ai_gate.schema.json : bornes snake_case et garde offline WAN refusée", () => {
    const normalized = normalizeAiGateConfig({
      provider: "AUTO",
      offline_mode: true,
      cloud_fallback: true,
      jev: { base_url: "https://api.typesafe.ai/v1/systemone" },
      djev: {
        mode: "ENFORCING",
        timeout_s: 0,
        api_key_env: "",
        cloud_fallback: true,
        min_upgrade_confidence: 2,
        min_downgrade_confidence: -1,
      },
    });

    expect(normalized.provider).toBe("auto");
    expect(normalized.offlineMode).toBe(true);
    // Offline strict : aucun egress WAN (fallbacks tombés, Djev marqué offline).
    expect(normalized.cloudFallback).toBe(false);
    expect(normalized.djev.cloudFallback).toBe(false);
    expect(normalized.djev.offlineMode).toBe(true);
    // Base Jev non-loopback rebasculée sur le proxy loopback (miroir ai_router._auto).
    expect(normalized.jev.baseUrl).toBe("http://127.0.0.1:4000");
    expect(isLoopbackUrl(normalized.jev.baseUrl)).toBe(true);
    expect(normalized.djev.mode).toBe("enforcing");
    expect(normalized.djev.timeoutS).toBe(5.0);
    expect(normalized.djev.apiKeyEnv).toBe("TYPESAFE_API_KEY");
    expect(normalized.djev.minUpgradeConfidence).toBe(1);
    expect(normalized.djev.minDowngradeConfidence).toBe(0);
  });

  it("presets LAN prioritaire / Offline strict / Cloud fallback autorisé", () => {
    const base = createDefaultAiGateConfig();

    const lan = applyAiGatePreset(base, "lan");
    expect(lan.offlineMode).toBe(false);
    expect(lan.cloudFallback).toBe(false);
    expect(lan.djev.baseUrl).toBe("http://127.0.0.1:4000");

    const offline = applyAiGatePreset(
      { ...base, djev: { ...base.djev, baseUrl: "https://api.typesafe.ai/v1/systemone" } },
      "offline"
    );
    expect(offline.offlineMode).toBe(true);
    expect(offline.cloudFallback).toBe(false);
    expect(isLoopbackUrl(offline.jev.baseUrl)).toBe(true);

    const cloud = applyAiGatePreset(base, "cloud");
    expect(cloud.offlineMode).toBe(false);
    expect(cloud.cloudFallback).toBe(true);
    expect(cloud.djev.cloudFallback).toBe(true);
    expect(cloud.djev.baseUrl).toBe("https://api.typesafe.ai/v1/systemone");
  });

  it("sérialise en snake_case avec le NOM de var uniquement, jamais la valeur", () => {
    const persistable = toPersistableAiGateConfig(createDefaultAiGateConfig());
    expect(persistable.offline_mode).toBe(true);
    expect(persistable.cloud_fallback).toBe(false);
    const djev = persistable.djev as Record<string, unknown>;
    expect(djev.api_key_env).toBe("TYPESAFE_API_KEY");
    expect("api_key" in djev).toBe(false);
    expect(JSON.stringify(persistable)).not.toContain("sk-");
  });

  it("round-trip snake_case sans perte des seuils par risque", () => {
    const before = normalizeAiGateConfig({
      provider: "djev",
      djev: {
        min_upgrade_confidence: 0.45,
        min_downgrade_confidence: 0.55,
        risky_threshold: 0.75,
      },
    });
    const after = normalizeAiGateConfig(toPersistableAiGateConfig(before));
    expect(after.provider).toBe("djev");
    expect(after.djev.minUpgradeConfidence).toBe(0.45);
    expect(after.djev.minDowngradeConfidence).toBe(0.55);
    expect(after.djev.riskyThreshold).toBe(0.75);
  });
});
