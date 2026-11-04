import { queryOptions } from "@tanstack/react-query";

import { isActive } from "@/features/enrichment/api";
import { api, unwrap, type Schemas } from "@/lib/api/client";

export type CompanyBrief = Schemas["CompanyBriefOut"];
export type Brief = Schemas["BriefOut"];
export type BriefRun = Schemas["BriefRunOut"];
export type BriefClaim = Schemas["ClaimOut"];
export type BriefCitation = Schemas["CitationOut"];
export type BriefSource = Schemas["BriefSourceOut"];
export type AIUsage = Schemas["AIUsageOut"];

export const insightKeys = {
  // Under "companies" so that editing a company re-checks whether its brief is out of date.
  brief: (id: string) => ["companies", "brief", id] as const,
  usage: ["ai", "usage"] as const,
};

export function briefQuery(companyId: string) {
  return queryOptions({
    queryKey: insightKeys.brief(companyId),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/companies/{company_id}/brief", {
          signal,
          params: { path: { company_id: companyId } },
        }),
      ),
    // Poll while the worker writes the brief; stop when the run has finished.
    refetchInterval: (query) => (isActive(query.state.data?.latest_run) ? 2000 : false),
  });
}

export const aiUsageQuery = queryOptions({
  queryKey: insightKeys.usage,
  queryFn: ({ signal }) => unwrap(api.GET("/ai/usage", { signal })),
});

export function requestBrief(companyId: string): Promise<BriefRun> {
  return unwrap(
    api.POST("/companies/{company_id}/brief", { params: { path: { company_id: companyId } } }),
  );
}

export const BRIEF_FAILURES: Record<string, string> = {
  llm_refused: "The AI model declined to write this brief.",
  llm_incomplete: "The AI model's answer was incomplete. Try again.",
  llm_error: "The AI service couldn't be reached. Try again in a minute.",
  company_missing: "The company no longer exists.",
  internal_error: "Something went wrong on our side. Try again.",
};

export const PURPOSE_LABELS: Record<string, string> = {
  company_profile: "Website enrichment",
  account_brief: "Account briefs",
};
