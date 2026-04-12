import type { ConfigLabPresetPack, ConfigLabBenchmarkSuiteId } from "./types";

const CONFIG_LAB_PRESET_PACKS: ConfigLabPresetPack[] = [
  {
    id: "baseline_workbench",
    label: "Atelier de base",
    family: "baseline",
    description: "Pack d'étude SRP heads-up et probe turn pour validation rapide et revue de lines.",
    treePresetIds: ["srp_hu_100bb", "srp_hu_texture_wet", "turn_probe_hu", "turn_delayed_cbet_hu"],
    benchmarkSuites: ["native_solve", "http_parity", "pokerkit_validation"],
    recommended: true,
    tags: ["baseline", "heads_up", "study"],
  },
  {
    id: "pressure_workbench",
    label: "Atelier pression",
    family: "pressure",
    description: "Scénarios 3-bet et 4-bet pour ranges condensées et stress test solver.",
    treePresetIds: ["3bp_hu_100bb", "4bp_hu_100bb"],
    benchmarkSuites: ["native_solve", "http_parity"],
    recommended: true,
    tags: ["pressure", "3bet", "4bet"],
  },
  {
    id: "endgame_workbench",
    label: "Atelier endgame",
    family: "endgame",
    description: "Spots de fin de coup river et low SPR pour analyse jam ou check.",
    treePresetIds: ["river_jam_low_spr", "river_overbet_polar_hu"],
    benchmarkSuites: ["native_solve", "http_parity", "rlcard_offline"],
    recommended: false,
    tags: ["river", "endgame", "low_spr"],
  },
  {
    id: "benchmark_suite",
    label: "Suite de benchmarks",
    family: "benchmark",
    description: "Pack combiné pour contrôles de parité solver, validation et boucles d'étude hors ligne.",
    treePresetIds: [
      "srp_hu_100bb",
      "srp_hu_texture_wet",
      "3bp_hu_100bb",
      "4bp_hu_100bb",
      "turn_probe_hu",
      "turn_delayed_cbet_hu",
      "river_jam_low_spr",
      "river_overbet_polar_hu",
    ],
    benchmarkSuites: [
      "native_solve",
      "http_parity",
      "pokerkit_validation",
      "rlcard_offline",
      "llm_assist_smoke",
    ],
    recommended: false,
    tags: ["benchmark", "validation", "offline"],
  },
];

const DEFAULT_CONFIG_LAB_PRESET_PACK_ID = "baseline_workbench";

export function listConfigLabPresetPacks(): ConfigLabPresetPack[] {
  return CONFIG_LAB_PRESET_PACKS.map((pack) => ({
    ...pack,
    treePresetIds: [...pack.treePresetIds],
    benchmarkSuites: [...pack.benchmarkSuites],
    tags: [...pack.tags],
  }));
}

export function getConfigLabPresetPack(packId: string | null | undefined): ConfigLabPresetPack {
  const matched = CONFIG_LAB_PRESET_PACKS.find((pack) => pack.id === packId);
  const pack = matched ?? CONFIG_LAB_PRESET_PACKS[0];
  return {
    ...pack,
    treePresetIds: [...pack.treePresetIds],
    benchmarkSuites: [...pack.benchmarkSuites],
    tags: [...pack.tags],
  };
}

export function getDefaultConfigLabPresetPackId(): string {
  return DEFAULT_CONFIG_LAB_PRESET_PACK_ID;
}

export function isConfigLabPresetPackId(value: string): boolean {
  return CONFIG_LAB_PRESET_PACKS.some((pack) => pack.id === value);
}

export function getConfigLabBenchmarkSuitesForPack(
  packId: string | null | undefined
): ConfigLabBenchmarkSuiteId[] {
  return [...getConfigLabPresetPack(packId).benchmarkSuites];
}
