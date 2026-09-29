import { LlmAssistTask, LlmConfig, type DjevOutputQuestion, type DjevQuestionSet } from "./types";
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

const DJEV_NOT_STATED = "not stated";
const DJEV_OTHER = "other";

/**
 * Questions Djev typees pour la sortie assistee (System One : choice / score /
 * noul). Exportees une par cle de sortie (summary, recommendations, warnings,
 * confidence + usedContext). Les instructions sont litterales (copie exacte
 * envoyee au modele), chaque question porte ses criteria, ses cas limites
 * (boundaryCases) et les options explicites "other" / "not stated".
 */
export const DJEV_SUMMARY_QUESTION: DjevOutputQuestion = {
  key: "summary",
  type: "score",
  instructions:
    "Rate how complete and coherent the operator-facing summary is: it must state the spot, the chosen line, and the one decisive reason, with no invented card, pot, or action.",
  criteria: [
    "0.0-0.3: Summary missing the spot or the chosen line, or contradicts the sanitized task context.",
    "0.4-0.6: Spot and line present but the decisive reason is vague or generic.",
    "0.7-1.0: Spot, chosen line, and the one decisive reason stated compactly and grounded in the sanitized context.",
  ],
  boundaryCases: [
    "Empty sanitized context: score low and answer 'not stated', never invent the spot.",
    "OCR or fallback diagnostic task: the decisive reason must name the observed symptom, not a guessed cause.",
  ],
  options: [DJEV_OTHER, DJEV_NOT_STATED],
};

export const DJEV_RECOMMENDATIONS_QUESTION: DjevOutputQuestion = {
  key: "recommendations",
  type: "choice",
  instructions:
    "Which recommendation set best fits the sanitized task context? Pick exactly one option; use 'other' only if no listed option fits, 'not stated' only if the context is empty.",
  criteria: {
    continue_current_line:
      "The sanitized context supports the current line; recommend at most one small adjustment.",
    adjust_sizing_or_frequency:
      "The context shows a sizing or frequency leak; recommend one concrete adjustment with its trigger.",
    switch_line:
      "The context contradicts the current line; recommend the alternative line and the observation that would confirm it.",
    gather_more_context:
      "The context is too thin or degraded (OCR, missing stack, partial history); recommend which single field to re-verify first.",
    [DJEV_OTHER]:
      "None of the listed recommendation sets fits the sanitized context.",
    [DJEV_NOT_STATED]:
      "The sanitized context is empty; no recommendation can be grounded.",
  },
  boundaryCases: [
    "Empty allowedScopes: answer 'not stated', never recommend a line.",
    "Strategy or session task with no single spot: prefer 'gather_more_context' over inventing a line switch.",
  ],
  options: [
    "continue_current_line",
    "adjust_sizing_or_frequency",
    "switch_line",
    "gather_more_context",
    DJEV_OTHER,
    DJEV_NOT_STATED,
  ],
};

export const DJEV_WARNINGS_QUESTION: DjevOutputQuestion = {
  key: "warnings",
  type: "noul",
  instructions:
    "Flag whether acting on the current model output risks an irreversible costly mistake (wrong line, misclicked sizing, acting on degraded OCR, or trusting an unparsed fallback response).",
  criteria: [
    "noul near 0: Context is complete and coherent; acting on the output is reversible or cheap.",
    "noul near 1: Context is degraded, contradictory, or missing (OCR, fallback, partial history); acting now risks real cost.",
  ],
  boundaryCases: [
    "Provider returned raw text instead of structured JSON: treat as high risk, never low.",
    "Strict-local privacy mode with full context: risk comes from the spot itself, not from redaction.",
  ],
  options: [DJEV_OTHER, DJEV_NOT_STATED],
};

export const DJEV_CONFIDENCE_USED_CONTEXT_QUESTION: DjevOutputQuestion = {
  key: "confidence",
  type: "noul",
  instructions:
    "Judge whether the stated confidence and the listed usedContext are grounded: confidence must match the completeness of the sanitized context actually cited, with no uncited field claimed.",
  criteria: [
    "noul near 0: Confidence is overstated or usedContext cites fields absent from the sanitized context.",
    "noul near 1: Confidence matches context completeness and every usedContext entry is present in the sanitized task context.",
  ],
  boundaryCases: [
    "Empty usedContext with high confidence: answer low, confidence is ungrounded.",
    "Redacted-remote mode: redacted labels still count as cited only if their rank/suit/position fields are present.",
  ],
  options: [DJEV_OTHER, DJEV_NOT_STATED],
};

export const DJEV_OUTPUT_QUESTIONS: DjevQuestionSet = {
  summary: DJEV_SUMMARY_QUESTION,
  recommendations: DJEV_RECOMMENDATIONS_QUESTION,
  warnings: DJEV_WARNINGS_QUESTION,
  confidence: DJEV_CONFIDENCE_USED_CONTEXT_QUESTION,
};

export function buildDjevQuestions(): DjevQuestionSet {
  return {
    summary: { ...DJEV_SUMMARY_QUESTION, criteria: [...DJEV_SUMMARY_QUESTION.criteria as string[]] },
    recommendations: {
      ...DJEV_RECOMMENDATIONS_QUESTION,
      criteria: { ...(DJEV_RECOMMENDATIONS_QUESTION.criteria as Record<string, string>) },
    },
    warnings: { ...DJEV_WARNINGS_QUESTION, criteria: [...DJEV_WARNINGS_QUESTION.criteria as string[]] },
    confidence: {
      ...DJEV_CONFIDENCE_USED_CONTEXT_QUESTION,
      criteria: [...DJEV_CONFIDENCE_USED_CONTEXT_QUESTION.criteria as string[]],
    },
  };
}

