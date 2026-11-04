import { queryOptions } from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "@/lib/api/client";

export type ICP = Schemas["ICPOut"];
export type ICPDefinition = Schemas["ICPDefinition"];
export type Criterion = ICPDefinition["criteria"][number];
export type CriterionKind = Criterion["kind"];
export type ICPPreview = Schemas["ICPPreview"];
export type CompanyScore = Schemas["CompanyScoreOut"];
export type Tier = CompanyScore["tier"];
export type BusinessModel = Schemas["BusinessModelCriterion"]["models"][number];

export const scoringKeys = {
  icp: ["icp"] as const,
  preview: (definition: ICPDefinition) => ["icp", "preview", definition] as const,
  // Under "companies" so that editing a company also refreshes its score.
  companyScore: (id: string) => ["companies", "score", id] as const,
  allScores: ["companies", "score"] as const,
};

export function isRescoring(icp: ICP | null | undefined): boolean {
  return !!icp && icp.status.scored_current < icp.status.total_companies;
}

export const icpQuery = queryOptions({
  queryKey: scoringKeys.icp,
  queryFn: ({ signal }) => unwrap(api.GET("/icp", { signal })),
  // While the background job rescores companies, poll to show progress.
  refetchInterval: (query) => (isRescoring(query.state.data) ? 2000 : false),
});

export function previewQuery(definition: ICPDefinition) {
  return queryOptions({
    queryKey: scoringKeys.preview(definition),
    queryFn: ({ signal }) => unwrap(api.POST("/icp/preview", { signal, body: definition })),
    staleTime: 30_000,
  });
}

export function companyScoreQuery(companyId: string) {
  return queryOptions({
    queryKey: scoringKeys.companyScore(companyId),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/companies/{company_id}/score", {
          signal,
          params: { path: { company_id: companyId } },
        }),
      ),
    // An out-of-date score is being recalculated in the background: check back shortly.
    refetchInterval: (query) => (query.state.data?.current === false ? 3000 : false),
  });
}

export function saveIcp(definition: ICPDefinition): Promise<ICP> {
  return unwrap(api.PUT("/icp", { body: definition }));
}

export async function deleteIcp(): Promise<void> {
  await unwrap(api.DELETE("/icp"));
}

export async function rescoreAll(): Promise<void> {
  await unwrap(api.POST("/icp/rescore"));
}

// --- Labels ------------------------------------------------------------------------------------

export const CRITERION_LABELS: Record<CriterionKind, string> = {
  industry: "Industry",
  size: "Company size",
  country: "Country",
  business_model: "Business model",
  keywords: "Keywords",
  has_contacts: "Contacts on file",
};

export const IMPORTANCE_LABELS: Record<number, string> = {
  1: "Minor",
  2: "Low",
  3: "Medium",
  4: "High",
  5: "Critical",
};

export const BUSINESS_MODELS: BusinessModel[] = ["B2B", "B2C", "B2B and B2C", "Marketplace"];

/** The industries the AI profile uses (backend: enrichment/extraction.py `Industry`). */
export const AI_INDUSTRIES = [
  "Software",
  "Fintech",
  "Banking & Insurance",
  "Healthcare",
  "Pharma & Biotech",
  "Manufacturing",
  "Energy & Utilities",
  "Retail & E-commerce",
  "Consumer Goods",
  "Logistics & Transportation",
  "Telecommunications",
  "Media & Entertainment",
  "Education",
  "Real Estate & Construction",
  "Professional Services",
  "Cybersecurity",
  "Hardware & Electronics",
  "Automotive",
  "Food & Beverage",
  "Travel & Hospitality",
  "Public Sector & Nonprofit",
];

export const TIERS: Tier[] = ["A", "B", "C", "D"];

export const TIER_DESCRIPTIONS: Record<Tier, string> = {
  A: "Excellent fit (75–100)",
  B: "Good fit (50–74)",
  C: "Weak fit (25–49)",
  D: "Poor fit (0–24)",
};
