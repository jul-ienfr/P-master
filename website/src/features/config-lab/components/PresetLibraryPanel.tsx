import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  Grid,
  Stack,
  Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import { getPresetLibraryCopy } from "../../../lib/workstationI18n";

export type PresetPackState = "active" | "ready" | "beta" | "locked";

export interface PresetPackItem {
  id: string;
  name: string;
  description: string;
  version?: string;
  status?: PresetPackState;
  tag?: string;
  coverage?: string;
  memoryFootprint?: string;
  solveTime?: string;
}

export interface PresetLibraryPanelProps {
  title?: string;
  subtitle?: string;
  locale?: "en" | "fr";
  packs: PresetPackItem[];
  activePackId: string;
  loading?: boolean;
  onSelectPack: (packId: string) => void;
  onRefresh?: () => void;
  onCreatePreset?: () => void;
  onOpenBenchmarks?: () => void;
}

const statusTone: Record<PresetPackState, "success" | "info" | "warning" | "default"> = {
  active: "success",
  ready: "info",
  beta: "warning",
  locked: "default",
};

function formatPackStatus(status: PresetPackState | undefined, locale: "en" | "fr") {
  const nextStatus = status ?? "ready";
  if (locale === "fr") {
    if (nextStatus === "active") return "actif";
    if (nextStatus === "ready") return "pret";
    if (nextStatus === "beta") return "beta";
    return "verrouille";
  }
  return nextStatus;
}

export function PresetLibraryPanel({
  title = "Preset Library",
  subtitle = "Curated packs for preflop, postflop and lab workflows.",
  locale = "en",
  packs,
  activePackId,
  loading = false,
  onSelectPack,
  onRefresh,
  onCreatePreset,
  onOpenBenchmarks,
}: PresetLibraryPanelProps) {
  const copy = getPresetLibraryCopy(locale);
  const activePack = packs.find((pack) => pack.id === activePackId);

  return (
    <Card
      elevation={0}
      sx={(theme) => ({
        borderRadius: 4,
        overflow: "hidden",
        border: 1,
        borderColor: "divider",
        background:
          theme.palette.mode === "dark"
            ? "linear-gradient(180deg, rgba(10,20,35,0.92) 0%, rgba(15,24,38,0.9) 100%)"
            : "linear-gradient(180deg, rgba(255,255,255,0.94) 0%, rgba(247,249,252,0.98) 100%)",
        boxShadow: `0 18px 60px ${alpha(
          theme.palette.common.black,
          theme.palette.mode === "dark" ? 0.22 : 0.08
        )}`,
      })}
    >
      <CardContent sx={{ p: 3 }}>
        <Stack spacing={2.5}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2} justifyContent="space-between">
            <Box>
              <Typography variant="overline" sx={{ letterSpacing: 1.8, color: "text.secondary" }}>
                Config Lab
              </Typography>
              <Typography variant="h5" sx={{ fontWeight: 800, letterSpacing: -0.4 }}>
                {title}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, maxWidth: 760 }}>
                {subtitle}
              </Typography>
            </Box>
            <Stack direction="row" spacing={1} flexWrap="wrap" justifyContent={{ xs: "flex-start", sm: "flex-end" }}>
              <Button variant="outlined" onClick={onRefresh} disabled={loading}>
                {copy.refresh}
              </Button>
              <Button variant="outlined" onClick={onOpenBenchmarks} disabled={loading}>
                {copy.benchmarks}
              </Button>
              <Button variant="contained" onClick={onCreatePreset} disabled={loading}>
                {copy.newPreset}
              </Button>
            </Stack>
          </Stack>

          <Divider />

          <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
            <Chip label={copy.packs(packs.length)} color="default" variant="outlined" />
            <Chip
              label={activePack ? copy.active(activePack.name) : copy.noActive}
              color={activePack ? "success" : "default"}
              variant="outlined"
            />
            <Chip label={copy.labReady} color="info" variant="outlined" />
          </Stack>

          <Grid container spacing={2}>
            {packs.map((pack) => {
              const selected = pack.id === activePackId;
              return (
                <Grid key={pack.id} item xs={12} md={6} lg={4}>
                  <Card
                    variant="outlined"
                    onClick={() => onSelectPack(pack.id)}
                    sx={(theme) => ({
                      height: "100%",
                      cursor: "pointer",
                      transition: "transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease",
                      borderColor: selected ? "primary.main" : "divider",
                      bgcolor:
                        selected
                          ? alpha(
                              theme.palette.primary.main,
                              theme.palette.mode === "dark" ? 0.18 : 0.06
                            )
                          : theme.palette.background.paper,
                      "&:hover": {
                        transform: "translateY(-2px)",
                        boxShadow: `0 10px 30px ${alpha(theme.palette.common.black, 0.08)}`,
                      },
                    })}
                  >
                    <CardContent sx={{ display: "flex", flexDirection: "column", gap: 1.5, minHeight: 180 }}>
                      <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1}>
                        <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>
                          {pack.name}
                        </Typography>
                        <Chip
                          size="small"
                          label={formatPackStatus(pack.status, locale)}
                          color={statusTone[pack.status ?? "ready"]}
                          variant="outlined"
                        />
                      </Stack>

                      <Typography variant="body2" color="text.secondary">
                        {pack.description}
                      </Typography>

                      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                        {pack.tag ? <Chip size="small" label={pack.tag} /> : null}
                        {pack.version ? <Chip size="small" label={`v${pack.version}`} /> : null}
                        {pack.coverage ? <Chip size="small" label={pack.coverage} /> : null}
                      </Stack>

                      <Stack spacing={0.5} sx={{ mt: "auto" }}>
                        {pack.solveTime ? (
                          <Typography variant="caption" color="text.secondary">
                            {copy.solveProfile}: {pack.solveTime}
                          </Typography>
                        ) : null}
                        {pack.memoryFootprint ? (
                          <Typography variant="caption" color="text.secondary">
                            {copy.memory}: {pack.memoryFootprint}
                          </Typography>
                        ) : null}
                      </Stack>
                    </CardContent>
                  </Card>
                </Grid>
              );
            })}
          </Grid>
        </Stack>
      </CardContent>
    </Card>
  );
}
