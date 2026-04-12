import { useDeferredValue } from "react";
import AddRoundedIcon from "@mui/icons-material/AddRounded";
import AutoAwesomeRoundedIcon from "@mui/icons-material/AutoAwesomeRounded";
import CasinoRoundedIcon from "@mui/icons-material/CasinoRounded";
import DeleteOutlineRoundedIcon from "@mui/icons-material/DeleteOutlineRounded";
import HistoryRoundedIcon from "@mui/icons-material/HistoryRounded";
import SpeedRoundedIcon from "@mui/icons-material/SpeedRounded";
import TuneRoundedIcon from "@mui/icons-material/TuneRounded";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Divider from "@mui/material/Divider";
import FormControl from "@mui/material/FormControl";
import FormHelperText from "@mui/material/FormHelperText";
import Grid from "@mui/material/Grid";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Paper from "@mui/material/Paper";
import Select, { SelectChangeEvent } from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

export interface SpotActionHistoryEntry {
  actor: string;
  action: string;
  size: string;
  note: string;
}

export interface SpotBuilderDraft {
  heroRange: string;
  villainRanges: string[];
  boardCards: string[];
  startingPot: number;
  effectiveStack: number;
  heroPosition: string;
  actionHistory: SpotActionHistoryEntry[];
  treePresetId: string;
  numPlayers: number;
  timeBudgetMs: number;
}

export interface SpotBuilderPresetOption {
  value: string;
  label: string;
  description?: string;
}

export interface SpotBuilderPositionOption {
  value: string;
  label: string;
}

export interface SpotBuilderFormProps {
  value: SpotBuilderDraft;
  onChange: (nextValue: SpotBuilderDraft) => void;
  onSubmit?: (nextValue: SpotBuilderDraft) => void;
  onReset?: () => void;
  disabled?: boolean;
  loading?: boolean;
  maxVillainRanges?: number;
  maxActionHistoryItems?: number;
  presetOptions?: SpotBuilderPresetOption[];
  positionOptions?: SpotBuilderPositionOption[];
  title?: string;
  subtitle?: string;
  submitLabel?: string;
  resetLabel?: string;
  locale?: "en" | "fr";
}

type SpotBuilderCopy = {
  validation: {
    heroRangeEmpty: string;
    villainRangeEmpty: string;
    boardTooLong: string;
    minPlayers: string;
    positiveBudget: string;
  };
  chips: {
    solverPath: string;
    llmOff: string;
  };
  sections: {
    ranges: string;
    parameters: string;
    history: string;
    preview: string;
  };
  labels: {
    heroRange: string;
    villainRange: (index: number) => string;
    boardCards: string;
    startingPot: string;
    effectiveStack: string;
    heroPosition: string;
    treePreset: string;
    players: string;
    timeBudget: string;
    actor: string;
    action: string;
    size: string;
    note: string;
    preset: string;
    previewTitle: string;
    heroRangePreview: string;
    villainRangesPreview: string;
    boardPreview: string;
    actionFlow: string;
    positionPreview: string;
    playersPreview: string;
    potPreview: string;
    stackPreview: string;
    budgetPreview: string;
  };
  helper: {
    heroRange: string;
    villainPrimary: string;
    villainSecondary: string;
    boardCards: string;
    preset: string;
    noBoard: string;
    emptyHistory: string;
    previewIntro: string;
    noHeroRange: string;
    villainNotSet: (index: number) => string;
    boardNotSet: string;
    noActionFlow: string;
    pendingAction: string;
  };
  actions: {
    addLine: string;
    removeLine: string;
    solving: string;
  };
  placeholders: {
    actor: string;
    action: string;
    size: string;
    note: string;
  };
};

const SPOT_BUILDER_COPY: Record<"en" | "fr", SpotBuilderCopy> = {
  en: {
    validation: {
      heroRangeEmpty: "Hero range is required.",
      villainRangeEmpty: "At least one villain range is required.",
      boardTooLong: "Board cannot contain more than five cards.",
      minPlayers: "At least two players are required.",
      positiveBudget: "Time budget must be greater than zero.",
    },
    chips: {
      solverPath: "Solver path",
      llmOff: "LLM off",
    },
    sections: {
      ranges: "Who can have what?",
      parameters: "Hand context",
      history: "What already happened?",
      preview: "Preview",
    },
    labels: {
      heroRange: "Your possible hands",
      villainRange: (index) => `Opponent ${index} possible hands`,
      boardCards: "Board cards",
      startingPot: "Current pot",
      effectiveStack: "Effective stack",
      heroPosition: "Your position",
      treePreset: "Spot type",
      players: "Number of players",
      timeBudget: "Max time",
      actor: "Who acts",
      action: "What happens",
      size: "Size",
      note: "Note",
      preset: "Spot type",
      previewTitle: "Summary",
      heroRangePreview: "Hero",
      villainRangesPreview: "Villains",
      boardPreview: "Board",
      actionFlow: "Action flow",
      positionPreview: "Position",
      playersPreview: "Players",
      potPreview: "Pot",
      stackPreview: "Stack",
      budgetPreview: "Budget",
    },
    helper: {
      heroRange: "Examples: `AA,AKs,AQo` or one exact hand like `AhKh`.",
      villainPrimary: "Main opponent range.",
      villainSecondary: "Extra slot if you want to work on more than one opponent.",
      boardCards: "Use spaces or commas, for example `Ah Kd 3c`.",
      preset: "Choose the closest spot. You do not need to know the technical shortcut.",
      noBoard: "Board not set",
      emptyHistory: "Leave this empty if you want to solve from the current board only.",
      previewIntro: "Quick summary before sending the request.",
      noHeroRange: "No hero range yet.",
      villainNotSet: (index) => `V${index}: not set`,
      boardNotSet: "Board not set",
      noActionFlow: "No action entered yet.",
      pendingAction: "Line to complete",
    },
    actions: {
      addLine: "Add line",
      removeLine: "Remove line",
      solving: "Solving...",
    },
    placeholders: {
      actor: "Hero / BTN / BB",
      action: "bet / call / raise / check",
      size: "33% / 2.5x",
      note: "Optional note",
    },
  },
  fr: {
    validation: {
      heroRangeEmpty: "La range hero est obligatoire.",
      villainRangeEmpty: "Au moins une range vilain est obligatoire.",
      boardTooLong: "Le board ne peut pas dépasser cinq cartes.",
      minPlayers: "Il faut au moins deux joueurs.",
      positiveBudget: "Le budget temps doit être supérieur à zéro.",
    },
    chips: {
      solverPath: "Chemin solver",
      llmOff: "LLM hors chemin",
    },
    sections: {
      ranges: "Qui peut avoir quoi ?",
      parameters: "Contexte du coup",
      history: "Ce qui s'est déjà passé",
      preview: "Aperçu",
    },
    labels: {
      heroRange: "Tes mains possibles",
      villainRange: (index) => `Mains possibles de l’adversaire ${index}`,
      boardCards: "Cartes sur la table",
      startingPot: "Pot actuel",
      effectiveStack: "Tapis effectif",
      heroPosition: "Ta position",
      treePreset: "Type de spot",
      players: "Nombre de joueurs",
      timeBudget: "Temps max",
      actor: "Qui agit",
      action: "Ce qu'il fait",
      size: "Taille",
      note: "Note",
      preset: "Type de spot",
      previewTitle: "Résumé",
      heroRangePreview: "Héros",
      villainRangesPreview: "Vilains",
      boardPreview: "Tableau",
      actionFlow: "Séquence",
      positionPreview: "Position",
      playersPreview: "Joueurs",
      potPreview: "Pot",
      stackPreview: "Tapis",
      budgetPreview: "Budget",
    },
    helper: {
      heroRange: "Exemples : `AA,AKs,AQo` ou une main exacte comme `AhKh`.",
      villainPrimary: "Range principale de l’adversaire.",
      villainSecondary: "Emplacement en plus si tu veux travailler avec plusieurs adversaires.",
      boardCards: "Sépare les cartes par des espaces ou des virgules, par exemple `Ah Kd 3c`.",
      preset: "Choisis le type de spot le plus proche. Pas besoin de comprendre le raccourci technique.",
      noBoard: "Tableau non défini",
      emptyHistory: "Tu peux laisser vide si tu veux calculer depuis l’état actuel du board.",
      previewIntro: "Résumé rapide avant l’envoi.",
      noHeroRange: "Aucune range hero pour l’instant.",
      villainNotSet: (index) => `V${index}: non défini`,
      boardNotSet: "Tableau non défini",
      noActionFlow: "Aucune action saisie pour l’instant.",
      pendingAction: "Ligne à compléter",
    },
    actions: {
      addLine: "Ajouter",
      removeLine: "Supprimer la ligne",
      solving: "Calcul...",
    },
    placeholders: {
      actor: "Hero / BTN / BB",
      action: "bet / call / raise / check",
      size: "33% / 2.5x",
      note: "Note facultative",
    },
  },
};

const DEFAULT_PRESETS: SpotBuilderPresetOption[] = [
  {
    value: "srp_hu_100bb",
    label: "Pot relancé simple · 2 joueurs · 100 blindes",
    description: "Le cas standard pour un coup postflop simple.",
  },
  {
    value: "3bp_hu_100bb",
    label: "Pot 3-bet · 2 joueurs · 100 blindes",
    description: "Quand le coup a déjà été sur-relancé avant le flop.",
  },
  {
    value: "4bp_hu_100bb",
    label: "Pot 4-bet · 2 joueurs · 100 blindes",
    description: "Quand il y a eu encore plus d’action avant le flop.",
  },
  {
    value: "turn_probe_hu",
    label: "Turn après check au flop",
    description: "Pour les spots où personne n’a misé au flop.",
  },
  {
    value: "river_jam_low_spr",
    label: "River avec peu de tapis restant",
    description: "Pour les décisions tapis ou call en fin de coup.",
  },
];

const DEFAULT_POSITIONS: SpotBuilderPositionOption[] = [
  { value: "oop", label: "OOP" },
  { value: "ip", label: "IP" },
  { value: "sb", label: "SB" },
  { value: "bb", label: "BB" },
  { value: "btn", label: "BTN" },
  { value: "button", label: "Bouton" },
];

const DEFAULT_HISTORY_ENTRY: SpotActionHistoryEntry = {
  actor: "",
  action: "",
  size: "",
  note: "",
};

function cloneActionHistoryEntry(
  entry: Partial<SpotActionHistoryEntry> = {}
): SpotActionHistoryEntry {
  return {
    actor: entry.actor ?? "",
    action: entry.action ?? "",
    size: entry.size ?? "",
    note: entry.note ?? "",
  };
}

function parseCardTokens(value: string): string[] {
  return value
    .split(/[\s,;/|]+/)
    .map((token) => token.trim())
    .filter(Boolean)
    .slice(0, 5);
}

function formatBoardCards(cards: string[]): string {
  return cards.join(" ");
}

function clampCount(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) {
    return min;
  }
  return Math.min(max, Math.max(min, Math.round(value)));
}

function summarizeHistory(entry: SpotActionHistoryEntry): string {
  return [entry.actor, entry.action, entry.size, entry.note]
    .map((part) => part.trim())
    .filter(Boolean)
    .join(" ");
}

function sanitizeVillainRanges(ranges: string[], count: number): string[] {
  const slots = Array.from({ length: count }, (_, index) => ranges[index] ?? "");
  return slots;
}

function validationMessages(value: SpotBuilderDraft, copy: SpotBuilderCopy): string[] {
  const messages: string[] = [];

  if (!value.heroRange.trim()) {
    messages.push(copy.validation.heroRangeEmpty);
  }

  if (!value.villainRanges.some((item) => item.trim().length > 0)) {
    messages.push(copy.validation.villainRangeEmpty);
  }

  if (value.boardCards.length > 5) {
    messages.push(copy.validation.boardTooLong);
  }

  if (value.numPlayers < 2) {
    messages.push(copy.validation.minPlayers);
  }

  if (value.timeBudgetMs <= 0) {
    messages.push(copy.validation.positiveBudget);
  }

  return messages;
}

export function SpotBuilderForm({
  value,
  onChange,
  onSubmit,
  onReset,
  disabled = false,
  loading = false,
  maxVillainRanges = 5,
  maxActionHistoryItems = 12,
  presetOptions = DEFAULT_PRESETS,
  positionOptions = DEFAULT_POSITIONS,
  title = "Describe the hand",
  subtitle = "Fill in only the useful information, then run the calculation.",
  submitLabel = "Run solve",
  resetLabel = "Reset",
  locale = "en",
}: SpotBuilderFormProps) {
  const copy = SPOT_BUILDER_COPY[locale];
  const deferredBoardCards = useDeferredValue(value.boardCards);
  const deferredHeroRange = useDeferredValue(value.heroRange);
  const deferredVillainRanges = useDeferredValue(value.villainRanges);
  const deferredActionHistory = useDeferredValue(value.actionHistory);
  const issues = validationMessages(value, copy);
  const villainSlotCount = clampCount(value.numPlayers - 1, 1, maxVillainRanges);
  const visibleVillainRanges = sanitizeVillainRanges(value.villainRanges, villainSlotCount);

  const updateDraft = (patch: Partial<SpotBuilderDraft>) => {
    onChange({
      ...value,
      ...patch,
    });
  };

  const handleBoardChange = (nextValue: string) => {
    updateDraft({ boardCards: parseCardTokens(nextValue) });
  };

  const handleVillainRangeChange = (index: number, nextValue: string) => {
    const villainRanges = sanitizeVillainRanges(value.villainRanges, villainSlotCount);
    villainRanges[index] = nextValue;
    updateDraft({ villainRanges });
  };

  const handlePlayerCountChange = (event: SelectChangeEvent<number>) => {
    const numPlayers = clampCount(Number(event.target.value), 2, maxVillainRanges + 1);
    updateDraft({
      numPlayers,
      villainRanges: sanitizeVillainRanges(value.villainRanges, numPlayers - 1),
    });
  };

  const handleHistoryEntryChange = (
    index: number,
    field: keyof SpotActionHistoryEntry,
    nextValue: string
  ) => {
    const actionHistory = value.actionHistory.map((entry, entryIndex) =>
      entryIndex === index ? { ...entry, [field]: nextValue } : cloneActionHistoryEntry(entry)
    );
    updateDraft({ actionHistory });
  };

  const handleAddHistoryEntry = () => {
    if (value.actionHistory.length >= maxActionHistoryItems) {
      return;
    }
    updateDraft({
      actionHistory: [...value.actionHistory, cloneActionHistoryEntry()],
    });
  };

  const handleRemoveHistoryEntry = (index: number) => {
    updateDraft({
      actionHistory: value.actionHistory.filter((_, entryIndex) => entryIndex !== index),
    });
  };

  const canSubmit = !disabled && !loading && issues.length === 0;

  return (
    <Card
      sx={{
        borderRadius: 5,
        overflow: "hidden",
      }}
    >
      <CardContent sx={{ p: { xs: 2, md: 3 } }}>
        <Stack spacing={3}>
          <Stack
            direction={{ xs: "column", lg: "row" }}
            justifyContent="space-between"
            alignItems={{ xs: "flex-start", lg: "center" }}
            spacing={2}
          >
            <Box>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                <Chip
                  label={copy.chips.solverPath}
                  color="primary"
                  icon={<AutoAwesomeRoundedIcon fontSize="small" />}
                  sx={{ fontWeight: 700 }}
                />
                <Chip label={copy.chips.llmOff} variant="outlined" />
              </Stack>
              <Typography variant="h5">{title}</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 760, mt: 0.75 }}>
                {subtitle}
              </Typography>
            </Box>

            <Stack direction={{ xs: "column", sm: "row" }} spacing={1.25}>
              <Button
                variant="outlined"
                color="inherit"
                onClick={onReset}
                disabled={disabled || loading || !onReset}
              >
                {resetLabel}
              </Button>
              <Button
                variant="contained"
                color="primary"
                onClick={() => onSubmit?.(value)}
                disabled={!canSubmit || !onSubmit}
              >
                {loading ? copy.actions.solving : submitLabel}
              </Button>
            </Stack>
          </Stack>

          {issues.length > 0 ? (
            <Alert severity="warning">
              <Stack spacing={0.5}>
                {issues.map((issue) => (
                  <span key={issue}>{issue}</span>
                ))}
              </Stack>
            </Alert>
          ) : null}

          <Grid container spacing={2.5}>
            <Grid item xs={12} xl={8}>
              <Stack spacing={2.5}>
                <Paper
                  sx={{
                    p: { xs: 2, md: 2.5 },
                    borderRadius: 4,
                    background:
                      "linear-gradient(180deg, rgba(14, 28, 44, 0.92), rgba(9, 18, 30, 0.84))",
                  }}
                >
                  <Stack spacing={2}>
                    <Stack direction="row" spacing={1} alignItems="center">
                      <CasinoRoundedIcon color="primary" />
                      <Typography variant="h6">{copy.sections.ranges}</Typography>
                    </Stack>
                    <Grid container spacing={2}>
                      <Grid item xs={12}>
                        <TextField
                          fullWidth
                          label={copy.labels.heroRange}
                          multiline
                          minRows={3}
                          value={value.heroRange}
                          disabled={disabled}
                          onChange={(event) => updateDraft({ heroRange: event.target.value })}
                          helperText={copy.helper.heroRange}
                        />
                      </Grid>

                      {visibleVillainRanges.map((villainRange, index) => (
                        <Grid item xs={12} md={visibleVillainRanges.length > 1 ? 6 : 12} key={index}>
                          <TextField
                            fullWidth
                            label={copy.labels.villainRange(index + 1)}
                            multiline
                            minRows={2}
                            value={villainRange}
                            disabled={disabled}
                            onChange={(event) => handleVillainRangeChange(index, event.target.value)}
                            helperText={
                              index === 0 ? copy.helper.villainPrimary : copy.helper.villainSecondary
                            }
                          />
                        </Grid>
                      ))}

                      <Grid item xs={12}>
                          <TextField
                            fullWidth
                            label={copy.labels.boardCards}
                            value={formatBoardCards(value.boardCards)}
                            disabled={disabled}
                            onChange={(event) => handleBoardChange(event.target.value)}
                            helperText={copy.helper.boardCards}
                          />
                        </Grid>

                      <Grid item xs={12}>
                        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                          {deferredBoardCards.length > 0 ? (
                            deferredBoardCards.map((card) => (
                              <Chip
                                key={card}
                                label={card}
                                color="secondary"
                                variant="outlined"
                                sx={{ letterSpacing: "0.08em" }}
                              />
                            ))
                          ) : (
                            <Chip label={copy.helper.noBoard} variant="outlined" />
                          )}
                        </Stack>
                      </Grid>
                    </Grid>
                  </Stack>
                </Paper>

                <Paper
                  sx={{
                    p: { xs: 2, md: 2.5 },
                    borderRadius: 4,
                  }}
                >
                  <Stack spacing={2}>
                    <Stack direction="row" spacing={1} alignItems="center">
                      <TuneRoundedIcon color="secondary" />
                      <Typography variant="h6">{copy.sections.parameters}</Typography>
                    </Stack>
                    <Grid container spacing={2}>
                      <Grid item xs={12} sm={6} lg={4}>
                        <TextField
                          fullWidth
                          label={copy.labels.startingPot}
                          type="number"
                          value={value.startingPot}
                          disabled={disabled}
                          onChange={(event) =>
                            updateDraft({ startingPot: Number(event.target.value) || 0 })
                          }
                          InputProps={{
                            endAdornment: <InputAdornment position="end">bb</InputAdornment>,
                          }}
                        />
                      </Grid>
                      <Grid item xs={12} sm={6} lg={4}>
                        <TextField
                          fullWidth
                          label={copy.labels.effectiveStack}
                          type="number"
                          value={value.effectiveStack}
                          disabled={disabled}
                          onChange={(event) =>
                            updateDraft({ effectiveStack: Number(event.target.value) || 0 })
                          }
                          InputProps={{
                            endAdornment: <InputAdornment position="end">bb</InputAdornment>,
                          }}
                        />
                      </Grid>
                      <Grid item xs={12} sm={6} lg={4}>
                        <FormControl fullWidth>
                          <InputLabel id="spot-builder-position-label">{copy.labels.heroPosition}</InputLabel>
                          <Select
                            labelId="spot-builder-position-label"
                            label={copy.labels.heroPosition}
                            value={value.heroPosition}
                            disabled={disabled}
                            onChange={(event) =>
                              updateDraft({ heroPosition: event.target.value as string })
                            }
                          >
                            {positionOptions.map((option) => (
                              <MenuItem key={option.value} value={option.value}>
                                {option.label}
                              </MenuItem>
                            ))}
                          </Select>
                        </FormControl>
                      </Grid>
                      <Grid item xs={12} sm={6} lg={4}>
                        <FormControl fullWidth>
                          <InputLabel id="spot-builder-preset-label">{copy.labels.treePreset}</InputLabel>
                          <Select
                            labelId="spot-builder-preset-label"
                            label={copy.labels.treePreset}
                            value={value.treePresetId}
                            disabled={disabled}
                            onChange={(event) =>
                              updateDraft({ treePresetId: event.target.value as string })
                            }
                          >
                            {presetOptions.map((option) => (
                              <MenuItem key={option.value} value={option.value}>
                                <Stack spacing={0.25}>
                                  <Typography variant="body2" fontWeight={700}>
                                    {option.label}
                                  </Typography>
                                  {option.description ? (
                                    <Typography variant="caption" color="text.secondary">
                                      {option.description}
                                    </Typography>
                                  ) : null}
                                </Stack>
                              </MenuItem>
                            ))}
                          </Select>
                          <FormHelperText>{copy.helper.preset}</FormHelperText>
                        </FormControl>
                      </Grid>
                      <Grid item xs={12} sm={6} lg={4}>
                        <FormControl fullWidth>
                          <InputLabel id="spot-builder-players-label">{copy.labels.players}</InputLabel>
                          <Select<number>
                            labelId="spot-builder-players-label"
                            label={copy.labels.players}
                            value={value.numPlayers}
                            disabled={disabled}
                            onChange={handlePlayerCountChange}
                          >
                            {Array.from({ length: maxVillainRanges }, (_, index) => index + 2).map(
                              (playerCount) => (
                                <MenuItem key={playerCount} value={playerCount}>
                                  {playerCount}
                                </MenuItem>
                              )
                            )}
                          </Select>
                        </FormControl>
                      </Grid>
                      <Grid item xs={12} sm={6} lg={4}>
                          <TextField
                            fullWidth
                            label={copy.labels.timeBudget}
                            type="number"
                          value={value.timeBudgetMs}
                          disabled={disabled}
                          onChange={(event) =>
                            updateDraft({ timeBudgetMs: Number(event.target.value) || 0 })
                          }
                          InputProps={{
                            startAdornment: (
                              <InputAdornment position="start">
                                <SpeedRoundedIcon fontSize="small" />
                              </InputAdornment>
                            ),
                            endAdornment: <InputAdornment position="end">ms</InputAdornment>,
                          }}
                        />
                      </Grid>
                    </Grid>
                  </Stack>
                </Paper>

                <Paper
                  sx={{
                    p: { xs: 2, md: 2.5 },
                    borderRadius: 4,
                  }}
                >
                  <Stack spacing={2}>
                    <Stack
                      direction={{ xs: "column", sm: "row" }}
                      justifyContent="space-between"
                      alignItems={{ xs: "flex-start", sm: "center" }}
                      spacing={1.5}
                    >
                        <Stack direction="row" spacing={1} alignItems="center">
                          <HistoryRoundedIcon color="primary" />
                          <Typography variant="h6">{copy.sections.history}</Typography>
                        </Stack>
                      <Button
                        variant="outlined"
                        startIcon={<AddRoundedIcon />}
                        onClick={handleAddHistoryEntry}
                        disabled={disabled || value.actionHistory.length >= maxActionHistoryItems}
                        >
                          {copy.actions.addLine}
                        </Button>
                      </Stack>

                    {value.actionHistory.length === 0 ? (
                      <Alert severity="info">
                        {copy.helper.emptyHistory}
                      </Alert>
                    ) : null}

                    <Stack spacing={1.5}>
                      {value.actionHistory.map((entry, index) => (
                        <Paper
                          key={`${index}:${summarizeHistory(entry)}`}
                          variant="outlined"
                          sx={{
                            p: 1.5,
                            borderRadius: 3,
                            backgroundColor: "rgba(255,255,255,0.02)",
                          }}
                        >
                          <Grid container spacing={1.25} alignItems="center">
                            <Grid item xs={12} sm={3}>
                              <TextField
                                fullWidth
                                label={copy.labels.actor}
                                value={entry.actor}
                                disabled={disabled}
                                onChange={(event) =>
                                  handleHistoryEntryChange(index, "actor", event.target.value)
                                }
                                placeholder={copy.placeholders.actor}
                              />
                            </Grid>
                            <Grid item xs={12} sm={3}>
                              <TextField
                                fullWidth
                                label={copy.labels.action}
                                value={entry.action}
                                disabled={disabled}
                                onChange={(event) =>
                                  handleHistoryEntryChange(index, "action", event.target.value)
                                }
                                placeholder={copy.placeholders.action}
                              />
                            </Grid>
                            <Grid item xs={12} sm={2}>
                              <TextField
                                fullWidth
                                label={copy.labels.size}
                                value={entry.size}
                                disabled={disabled}
                                onChange={(event) =>
                                  handleHistoryEntryChange(index, "size", event.target.value)
                                }
                                placeholder={copy.placeholders.size}
                              />
                            </Grid>
                            <Grid item xs={12} sm={3}>
                              <TextField
                                fullWidth
                                label={copy.labels.note}
                                value={entry.note}
                                disabled={disabled}
                                onChange={(event) =>
                                  handleHistoryEntryChange(index, "note", event.target.value)
                                }
                                placeholder={copy.placeholders.note}
                              />
                            </Grid>
                            <Grid item xs={12} sm={1}>
                              <Tooltip title={copy.actions.removeLine}>
                                <span>
                                  <IconButton
                                    color="error"
                                    onClick={() => handleRemoveHistoryEntry(index)}
                                    disabled={disabled}
                                  >
                                    <DeleteOutlineRoundedIcon />
                                  </IconButton>
                                </span>
                              </Tooltip>
                            </Grid>
                          </Grid>
                        </Paper>
                      ))}
                    </Stack>
                  </Stack>
                </Paper>
              </Stack>
            </Grid>

          </Grid>
        </Stack>
      </CardContent>
    </Card>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <Stack direction="row" justifyContent="space-between" spacing={2}>
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body2" fontWeight={700} textAlign="right">
        {value}
      </Typography>
    </Stack>
  );
}

function SummaryTimelineRow({ index, summary }: { index: number; summary: string }) {
  return (
    <Stack direction="row" spacing={1.25} alignItems="flex-start">
      <Chip
        label={index + 1}
        size="small"
        color="primary"
        sx={{ minWidth: 34, fontWeight: 700 }}
      />
      <Typography variant="body2" color="text.secondary">
        {summary}
      </Typography>
    </Stack>
  );
}

export default SpotBuilderForm;
