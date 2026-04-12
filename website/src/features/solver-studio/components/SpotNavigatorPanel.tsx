import {
  Box,
  Card,
  CardContent,
  Chip,
  Divider,
  List,
  ListItemButton,
  ListItemText,
  Stack,
  Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";

export interface SpotNavigatorEntry {
  id: string;
  title: string;
  subtitle?: string;
  board?: string[];
  tags?: string[];
  selected?: boolean;
  statusLabel?: string;
}

export interface CachedSolveEntry {
  id: string;
  title: string;
  action: string;
  presetId: string;
  board: string[];
  cacheHit: boolean;
  warnings: string[];
}

export interface SpotNavigatorPanelProps {
  locale?: "en" | "fr";
  spots: SpotNavigatorEntry[];
  selectedSpotId?: string;
  cachedSolves?: CachedSolveEntry[];
  onSelectSpot?: (spotId: string) => void;
}

export function SpotNavigatorPanel({
  locale = "en",
  spots,
  selectedSpotId,
  cachedSolves = [],
  onSelectSpot,
}: SpotNavigatorPanelProps) {
  const copy =
    locale === "fr"
      ? {
          title: "Navigateur de spots",
          subtitle: "Exemples, captures et solves recents disponibles pour la relecture.",
          library: "Bibliotheque de spots",
          replay: "Relecture des solves caches",
          emptySpots: "Aucun spot disponible.",
          emptyReplay: "Aucun solve memorise pour l’instant.",
          cacheHit: "Cache",
          fresh: "Frais",
        }
      : {
          title: "Spot navigator",
          subtitle: "Samples, captures, and recent solves available for quick review.",
          library: "Spot library",
          replay: "Cached solve replay",
          emptySpots: "No spots are available yet.",
          emptyReplay: "No cached solve is visible yet.",
          cacheHit: "Cached",
          fresh: "Fresh",
        };

  return (
    <Card
      variant="outlined"
      sx={(theme) => ({
        borderRadius: 5,
        overflow: "hidden",
        borderColor: alpha(theme.palette.text.primary, 0.08),
        background: `
          radial-gradient(circle at top right, ${alpha(theme.palette.primary.main, 0.12)}, transparent 28%),
          ${
            theme.palette.mode === "dark"
              ? "linear-gradient(180deg, rgba(9,16,27,0.96), rgba(8,13,22,0.94))"
              : "linear-gradient(180deg, rgba(255,255,255,0.96), rgba(247,249,252,0.98))"
          }
        `,
      })}
    >
      <CardContent sx={{ p: { xs: 2.25, md: 2.75 } }}>
        <Stack spacing={2.5}>
          <Box>
            <Typography variant="overline" color="text.secondary">
              Solver Studio
            </Typography>
            <Typography variant="h5">{copy.title}</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
              {copy.subtitle}
            </Typography>
          </Box>

          <Box>
            <Typography variant="subtitle2" sx={{ mb: 1.1 }}>
              {copy.library}
            </Typography>
            {spots.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                {copy.emptySpots}
              </Typography>
            ) : (
              <List disablePadding sx={{ display: "grid", gap: 1 }}>
                {spots.map((spot) => {
                  const selected = selectedSpotId ? selectedSpotId === spot.id : spot.selected;
                  return (
                    <ListItemButton
                      key={spot.id}
                      onClick={() => onSelectSpot?.(spot.id)}
                      sx={(theme) => ({
                        borderRadius: 3,
                        alignItems: "flex-start",
                        border: `1px solid ${
                          selected
                            ? alpha(theme.palette.primary.main, 0.45)
                            : alpha(theme.palette.text.primary, 0.08)
                        }`,
                        background: selected
                          ? `linear-gradient(180deg, ${alpha(theme.palette.primary.main, 0.12)}, ${alpha(
                              theme.palette.text.primary,
                              theme.palette.mode === "dark" ? 0.02 : 0.01
                            )})`
                          : alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.02 : 0.01),
                      })}
                    >
                      <ListItemText
                        primary={spot.title}
                        secondary={
                          <Stack spacing={0.9} sx={{ mt: 0.75 }}>
                            {spot.subtitle ? (
                              <Typography variant="body2" color="text.secondary">
                                {spot.subtitle}
                              </Typography>
                            ) : null}
                            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                              {spot.board && spot.board.length > 0 ? (
                                <Chip label={spot.board.join(" ")} size="small" variant="outlined" />
                              ) : null}
                              {spot.statusLabel ? <Chip label={spot.statusLabel} size="small" /> : null}
                              {(spot.tags ?? []).slice(0, 3).map((tag) => (
                                <Chip key={`${spot.id}-${tag}`} label={tag} size="small" variant="outlined" />
                              ))}
                            </Stack>
                          </Stack>
                        }
                      />
                    </ListItemButton>
                  );
                })}
              </List>
            )}
          </Box>

          <Divider />

          <Box>
            <Typography variant="subtitle2" sx={{ mb: 1.1 }}>
              {copy.replay}
            </Typography>
            {cachedSolves.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                {copy.emptyReplay}
              </Typography>
            ) : (
              <Stack spacing={1}>
                {cachedSolves.map((entry) => (
                  <Box
                    key={entry.id}
                    sx={(theme) => ({
                      borderRadius: 3,
                      px: 1.5,
                      py: 1.35,
                      border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
                      background: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.02 : 0.01),
                    })}
                  >
                    <Stack spacing={0.75}>
                      <Stack direction="row" justifyContent="space-between" spacing={1} flexWrap="wrap" useFlexGap>
                        <Typography variant="body2" sx={{ fontWeight: 700 }}>
                          {entry.title}
                        </Typography>
                        <Chip
                          label={entry.cacheHit ? copy.cacheHit : copy.fresh}
                          size="small"
                          color={entry.cacheHit ? "success" : "default"}
                          variant={entry.cacheHit ? "filled" : "outlined"}
                        />
                      </Stack>
                      <Typography variant="body2" color="text.secondary">
                        {entry.action} · {entry.presetId}
                      </Typography>
                      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                        <Chip label={entry.board.join(" ")} size="small" variant="outlined" />
                        {entry.warnings.slice(0, 2).map((warning) => (
                          <Chip key={`${entry.id}-${warning}`} label={warning} size="small" color="warning" variant="outlined" />
                        ))}
                      </Stack>
                    </Stack>
                  </Box>
                ))}
              </Stack>
            )}
          </Box>
        </Stack>
      </CardContent>
    </Card>
  );
}

export default SpotNavigatorPanel;
