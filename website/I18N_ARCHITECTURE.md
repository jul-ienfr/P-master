# I18N Architecture

This `website` workspace uses a lightweight, code-first i18n layer for the workstation GUI.

## Main entry points

- `src/lib/workstationI18n.ts`
  - public facade for copy access
  - shared localization helpers
  - `t(locale, selector)`
  - `useWorkstationText(locale)`

- `src/lib/i18n/workstationCopies.ts`
  - barrel file re-exporting domain copy modules

## Domain copy modules

- `src/lib/i18n/core.copy.ts`
  - workstation shell copy

- `src/lib/i18n/replay.copy.ts`
  - replay page and replay-related secondary panels

- `src/lib/i18n/config.copy.ts`
  - config-lab, runtime controls, OCR, presets

- `src/lib/i18n/bot.copy.ts`
  - bot cockpit and bot-related secondary panels

## Usage guidelines

- Prefer reusing existing domain copy exports before adding new inline labels.
- Add new UI copy to the domain module that owns the screen.
- Keep dynamic display normalization in `workstationI18n.ts` helpers.
- Prefer `t(locale, selector)` or `useWorkstationText(locale)` over repeated `locale === "fr" ? ... : ...` branches.

## Tests

- Primary i18n tests live in `src/lib/workstationI18n.test.ts`.
- Run them with `npm test`.
- Full validation remains `npm run build`.
