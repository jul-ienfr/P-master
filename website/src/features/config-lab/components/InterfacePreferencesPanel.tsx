import {
  Box,
  Card,
  CardContent,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import type { WorkstationThemeMode } from "../../../lib/theme";

type InterfaceLocale = "en" | "fr";

export interface InterfacePreferencesPanelProps {
  locale?: InterfaceLocale;
  activeLocale: InterfaceLocale;
  activeThemeMode: WorkstationThemeMode;
  onChangeLocale: (locale: InterfaceLocale) => void;
  onChangeThemeMode: (mode: WorkstationThemeMode) => void;
}

const LOCALES = ["fr", "en"] as const;
const THEMES = ["light", "dark"] as const;

export function InterfacePreferencesPanel({
  locale = "en",
  activeLocale,
  activeThemeMode,
  onChangeLocale,
  onChangeThemeMode,
}: InterfacePreferencesPanelProps) {
  const copy =
    locale === "fr"
      ? {
          kicker: "Interface",
          title: "Préférences rapides",
          subtitle: "Langue et thème sont déplacés ici pour alléger les écrans de travail.",
          language: "Langue",
          theme: "Thème",
          localeLabels: {
            fr: "FR",
            en: "EN",
          },
          themeLabels: {
            light: "Clair",
            dark: "Sombre",
          },
        }
      : {
          kicker: "Interface",
          title: "Quick preferences",
          subtitle: "Language and theme live here now to keep the work surfaces lighter.",
          language: "Language",
          theme: "Theme",
          localeLabels: {
            fr: "FR",
            en: "EN",
          },
          themeLabels: {
            light: "Light",
            dark: "Dark",
          },
        };

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
            ? "linear-gradient(180deg, rgba(14,22,33,0.98) 0%, rgba(10,16,25,0.94) 100%)"
            : "linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(246,249,252,0.98) 100%)",
        boxShadow: `0 18px 52px ${alpha(theme.palette.common.black, theme.palette.mode === "dark" ? 0.22 : 0.08)}`,
      })}
    >
      <CardContent sx={{ p: { xs: 2, md: 2.25 } }}>
        <Stack spacing={1.75}>
          <Box>
            <Typography variant="overline" sx={{ letterSpacing: 1.6, color: "text.secondary" }}>
              {copy.kicker}
            </Typography>
            <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>
              {copy.title}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.35, maxWidth: 680 }}>
              {copy.subtitle}
            </Typography>
          </Box>

          <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} useFlexGap>
            <Box sx={{ display: "grid", gap: 0.65, minWidth: 0 }}>
              <Typography
                variant="caption"
                sx={{ color: "text.secondary", textTransform: "uppercase", letterSpacing: 1 }}
              >
                {copy.language}
              </Typography>
              <ToggleButtonGroup
                exclusive
                size="small"
                value={activeLocale}
                onChange={(_event, value: InterfaceLocale | null) => {
                  if (value === "fr" || value === "en") {
                    onChangeLocale(value);
                  }
                }}
                sx={(theme) => ({
                  flexWrap: "wrap",
                  gap: 0.75,
                  "& .MuiToggleButton-root": {
                    borderRadius: 999,
                    border: `1px solid ${alpha(theme.palette.text.primary, 0.12)} !important`,
                    px: 1.25,
                    py: 0.55,
                    fontWeight: 700,
                    color: theme.palette.text.secondary,
                  },
                  "& .MuiToggleButton-root.Mui-selected": {
                    color: theme.palette.text.primary,
                    backgroundColor: alpha(
                      theme.palette.primary.main,
                      theme.palette.mode === "dark" ? 0.22 : 0.12
                    ),
                  },
                })}
              >
                {LOCALES.map((option) => (
                  <ToggleButton key={option} value={option}>
                    {copy.localeLabels[option]}
                  </ToggleButton>
                ))}
              </ToggleButtonGroup>
            </Box>

            <Box sx={{ display: "grid", gap: 0.65, minWidth: 0 }}>
              <Typography
                variant="caption"
                sx={{ color: "text.secondary", textTransform: "uppercase", letterSpacing: 1 }}
              >
                {copy.theme}
              </Typography>
              <ToggleButtonGroup
                exclusive
                size="small"
                value={activeThemeMode}
                onChange={(_event, value: WorkstationThemeMode | null) => {
                  if (value === "light" || value === "dark") {
                    onChangeThemeMode(value);
                  }
                }}
                sx={(theme) => ({
                  flexWrap: "wrap",
                  gap: 0.75,
                  "& .MuiToggleButton-root": {
                    borderRadius: 999,
                    border: `1px solid ${alpha(theme.palette.text.primary, 0.12)} !important`,
                    px: 1.25,
                    py: 0.55,
                    fontWeight: 700,
                    color: theme.palette.text.secondary,
                  },
                  "& .MuiToggleButton-root.Mui-selected": {
                    color: theme.palette.text.primary,
                    backgroundColor: alpha(
                      theme.palette.primary.main,
                      theme.palette.mode === "dark" ? 0.22 : 0.12
                    ),
                  },
                })}
              >
                {THEMES.map((option) => (
                  <ToggleButton key={option} value={option}>
                    {copy.themeLabels[option]}
                  </ToggleButton>
                ))}
              </ToggleButtonGroup>
            </Box>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}
