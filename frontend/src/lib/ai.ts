/** Why AI features may be unavailable, in plain language (shared by every AI feature). */
import { ApiError, type Schemas } from "@/lib/api/client";

export type AiUnavailableReason = NonNullable<Schemas["AIUsageOut"]["unavailable_reason"]>;

export const AI_UNAVAILABLE: Record<AiUnavailableReason, string> = {
  not_configured: "AI features aren't configured on this server yet.",
  disabled_for_org:
    "AI features aren't enabled for this workspace. Everything else works as usual.",
  budget_exhausted: "AI features are paused: this month's AI budget has been used up.",
};

/** The plain-language message for an `ai_unavailable` API error, or undefined. */
export function aiUnavailableMessage(error: unknown): string | undefined {
  if (!(error instanceof ApiError) || error.code !== "ai_unavailable") return undefined;
  const detail = error.details[0] as { reason?: string } | undefined;
  const reason = detail?.reason as AiUnavailableReason | undefined;
  return reason && reason in AI_UNAVAILABLE ? AI_UNAVAILABLE[reason] : error.message;
}

/** Failure reasons the worker records when it stops before calling the model. */
export const AI_RUN_FAILURES: Record<string, string> = {
  ai_disabled_for_org: AI_UNAVAILABLE.disabled_for_org,
  ai_budget_exhausted: AI_UNAVAILABLE.budget_exhausted,
};
