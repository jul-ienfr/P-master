import { LlmAssistTask, LlmConfig } from "./types";
import { sanitizeTaskForPrivacy } from "./privacy";

function taskGoal(kind: LlmAssistTask["kind"]): string {
  switch (kind) {
    case "spot_explain":
      return "Explain the poker spot clearly and compactly.";
    case "line_compare":
      return "Compare the available lines and highlight meaningful tradeoffs.";
    case "decision_rationale":
      return "Explain why the selected decision is reasonable and what the alternatives imply.";
    case "ocr_diagnostic":
      return "Diagnose OCR problems and suggest safe operator actions.";
    case "fallback_diagnostic":
      return "Diagnose the fallback path and suggest safe operational next steps.";
    case "session_summary":
      return "Summarize the session and highlight recurring patterns.";
    case "strategy_review":
      return "Review the current strategy setup and give actionable improvement ideas.";
    case "replay_coach":
      return "Coach the replay review and identify study spots.";
    default:
      return "Help with the current poker analysis task.";
  }
}

export function buildLlmMessages(task: LlmAssistTask, config: LlmConfig): Array<{ role: "system" | "user"; content: string }> {
  const sanitized = sanitizeTaskForPrivacy(task, config);
  const systemPrompt = [
    "You are a poker analysis copilot embedded in a local desktop workstation.",
    "You must never replace the deterministic solver or claim guaranteed profit.",
    "Keep the response safe, concise, and useful for an operator.",
    "Return plain JSON with the keys summary, recommendations, warnings, confidence, and usedContext.",
    `Task: ${taskGoal(task.kind)}`,
    `Privacy mode: ${config.privacyMode}`,
  ].join(" ");

  const userPrompt = JSON.stringify(
    {
      config: {
        providerMode: config.providerMode,
        model: config.model,
        temperature: config.temperature,
        maxOutputTokens: config.maxOutputTokens,
      },
      task: sanitized,
    },
    null,
    2
  );

  return [
    { role: "system", content: systemPrompt },
    { role: "user", content: userPrompt },
  ];
}

export function extractAssistantText(content: string | null | undefined): string {
  if (!content) {
    return "";
  }

  return content.trim();
}

