import type {
  SolverStudioSpot,
  SolverTreePreset,
  SolverTreePresetId,
} from "./types";

const SOLVER_TREE_PRESETS: SolverTreePreset[] = [
  {
    id: "srp_hu_100bb",
    label: "Pot relancé simple · 2 joueurs · 100 blindes",
    family: "srp",
    description: "Cas simple pour un coup postflop standard à deux joueurs.",
    defaultHeroPosition: "ip",
    defaultStreet: "flop",
    defaultStartingPot: 6.5,
    defaultEffectiveStack: 93.5,
    defaultBoard: ["Ah", "Kd", "7c"],
    defaultTimeBudgetMs: 1500,
    recommendedNumPlayers: 2,
    tags: ["baseline", "heads_up", "flop"],
  },
  {
    id: "srp_hu_texture_wet",
    label: "Pot relancé simple · board connecté",
    family: "srp",
    description: "Même base simple, mais avec un board plus dynamique.",
    defaultHeroPosition: "oop",
    defaultStreet: "flop",
    defaultStartingPot: 6.5,
    defaultEffectiveStack: 93.5,
    defaultBoard: ["Jh", "Th", "8c"],
    defaultTimeBudgetMs: 1700,
    recommendedNumPlayers: 2,
    tags: ["baseline", "wet_board", "flop"],
  },
  {
    id: "3bp_hu_100bb",
    label: "Pot 3-bet · 2 joueurs · 100 blindes",
    family: "3bet",
    description: "Pour les coups déjà sur-relancés avant le flop.",
    defaultHeroPosition: "oop",
    defaultStreet: "flop",
    defaultStartingPot: 22,
    defaultEffectiveStack: 78,
    defaultBoard: ["Qs", "9h", "4d"],
    defaultTimeBudgetMs: 1800,
    recommendedNumPlayers: 2,
    tags: ["3bet", "heads_up", "flop"],
  },
  {
    id: "4bp_hu_100bb",
    label: "Pot 4-bet · 2 joueurs · 100 blindes",
    family: "4bet",
    description: "Pour les coups très engagés avant le flop.",
    defaultHeroPosition: "ip",
    defaultStreet: "flop",
    defaultStartingPot: 40,
    defaultEffectiveStack: 60,
    defaultBoard: ["Jc", "7s", "2d"],
    defaultTimeBudgetMs: 2000,
    recommendedNumPlayers: 2,
    tags: ["4bet", "heads_up", "flop"],
  },
  {
    id: "turn_probe_hu",
    label: "Turn après check au flop",
    family: "turn",
    description: "Pour les spots où le flop a été checké et l'action démarre turn.",
    defaultHeroPosition: "oop",
    defaultStreet: "turn",
    defaultStartingPot: 9,
    defaultEffectiveStack: 88,
    defaultBoard: ["Kh", "8d", "3s", "2c"],
    defaultTimeBudgetMs: 1700,
    recommendedNumPlayers: 2,
    tags: ["turn", "probe", "heads_up"],
  },
  {
    id: "turn_delayed_cbet_hu",
    label: "Turn avec mise retardée",
    family: "turn",
    description: "Pour les spots où l'agresseur initial mise seulement turn.",
    defaultHeroPosition: "ip",
    defaultStreet: "turn",
    defaultStartingPot: 15,
    defaultEffectiveStack: 82,
    defaultBoard: ["Qc", "7d", "2s", "4h"],
    defaultTimeBudgetMs: 1650,
    recommendedNumPlayers: 2,
    tags: ["turn", "delay", "heads_up"],
  },
  {
    id: "river_jam_low_spr",
    label: "River avec peu de tapis restant",
    family: "river",
    description: "Pour les décisions tapis ou call avec peu de profondeur.",
    defaultHeroPosition: "ip",
    defaultStreet: "river",
    defaultStartingPot: 32,
    defaultEffectiveStack: 18,
    defaultBoard: ["Th", "8h", "4c", "2d", "2s"],
    defaultTimeBudgetMs: 1200,
    recommendedNumPlayers: 2,
    tags: ["river", "jam", "low_spr"],
  },
  {
    id: "river_overbet_polar_hu",
    label: "River avec très grosse mise",
    family: "river",
    description: "Pour les fins de coup avec option de grosse mise river.",
    defaultHeroPosition: "oop",
    defaultStreet: "river",
    defaultStartingPot: 38,
    defaultEffectiveStack: 52,
    defaultBoard: ["As", "Ts", "6d", "6c", "2h"],
    defaultTimeBudgetMs: 1450,
    recommendedNumPlayers: 2,
    tags: ["river", "overbet", "polar"],
  },
];

const DEFAULT_PRESET_ID: SolverTreePresetId = "srp_hu_100bb";

export function listSolverTreePresets(): SolverTreePreset[] {
  return SOLVER_TREE_PRESETS.map((preset) => ({
    ...preset,
    defaultBoard: [...preset.defaultBoard],
    tags: [...preset.tags],
  }));
}

export function getSolverTreePreset(
  presetId: SolverTreePresetId | null | undefined
): SolverTreePreset {
  const matched = SOLVER_TREE_PRESETS.find((preset) => preset.id === presetId);
  const preset = matched ?? SOLVER_TREE_PRESETS[0];
  return {
    ...preset,
    defaultBoard: [...preset.defaultBoard],
    tags: [...preset.tags],
  };
}

export function getDefaultSolverTreePresetId(): SolverTreePresetId {
  return DEFAULT_PRESET_ID;
}

export function isSolverTreePresetId(value: string): value is SolverTreePresetId {
  return SOLVER_TREE_PRESETS.some((preset) => preset.id === value);
}

export function applySolverTreePresetDefaults(
  spot: SolverStudioSpot,
  presetId: SolverTreePresetId
): SolverStudioSpot {
  const preset = getSolverTreePreset(presetId);
  return {
    ...spot,
    treePresetId: preset.id,
    heroPosition: spot.heroPosition ?? preset.defaultHeroPosition,
    startingPot: spot.startingPot > 0 ? spot.startingPot : preset.defaultStartingPot,
    effectiveStack:
      spot.effectiveStack > 0 ? spot.effectiveStack : preset.defaultEffectiveStack,
    board: spot.board.length > 0 ? [...spot.board] : [...preset.defaultBoard],
    numPlayers: spot.numPlayers > 0 ? spot.numPlayers : preset.recommendedNumPlayers,
    timeBudgetMs: spot.timeBudgetMs ?? preset.defaultTimeBudgetMs,
    street: spot.board.length > 0 ? spot.street : preset.defaultStreet,
    tags: Array.from(new Set([...preset.tags, ...spot.tags])),
  };
}
