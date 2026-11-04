import { queryOptions } from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "@/lib/api/client";

export type CompanyEnrichment = Schemas["CompanyEnrichmentOut"];
export type EnrichmentRun = Schemas["EnrichmentRunOut"];
export type EnrichmentUsage = Schemas["EnrichmentUsageOut"];

export const enrichmentKeys = {
  all: ["enrichment"] as const,
  company: (id: string) => ["enrichment", "company", id] as const,
  usage: ["enrichment", "usage"] as const,
};

export function isActive(run: EnrichmentRun | null | undefined): boolean {
  return run?.status === "queued" || run?.status === "running";
}

export function companyEnrichmentQuery(companyId: string) {
  return queryOptions({
    queryKey: enrichmentKeys.company(companyId),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/companies/{company_id}/enrichment", {
          signal,
          params: { path: { company_id: companyId } },
        }),
      ),
    // Poll while the worker is busy; stop as soon as the run has finished.
    refetchInterval: (query) => (isActive(query.state.data?.latest_run) ? 2000 : false),
  });
}

export const usageQuery = queryOptions({
  queryKey: enrichmentKeys.usage,
  queryFn: ({ signal }) => unwrap(api.GET("/enrichment/usage", { signal })),
});

export function enrichCompany(companyId: string): Promise<EnrichmentRun> {
  return unwrap(
    api.POST("/companies/{company_id}/enrich", { params: { path: { company_id: companyId } } }),
  );
}

export function enrichNotYetEnriched(): Promise<EnrichmentRun[]> {
  return unwrap(api.POST("/enrichment/runs", { body: { not_yet_enriched: true } }));
}

/** Plain-language explanations of why a run failed. */
export const FAILURE_MESSAGES: Record<string, string> = {
  no_website: "This company has no website or domain to read.",
  fetch_robots_disallowed: "The website asks automated tools not to read it (robots.txt).",
  fetch_blocked_address: "The website's address isn't on the public internet.",
  fetch_invalid_url: "The website address isn't valid.",
  fetch_timeout: "The website took too long to respond.",
  fetch_network_error: "The website couldn't be reached.",
  fetch_http_error: "The website returned an error page.",
  fetch_not_html: "The website address doesn't point to a web page.",
  fetch_too_large: "The website's pages are too large to read.",
  fetch_too_many_redirects: "The website redirects too many times.",
  fetch_no_text: "The website has too little readable text.",
  llm_refused: "The AI model declined this request.",
  llm_incomplete: "The AI model's answer was incomplete.",
  llm_error: "The AI service was unavailable. Try again later.",
  internal_error: "Something went wrong on our side.",
};

export const FACT_LABELS: Record<string, string> = {
  description: "What they do",
  industry: "Industry",
  products: "Products & services",
  target_customers: "Customers",
  business_model: "Business model",
  headquarters_city: "Headquarters (city)",
  headquarters_country: "Headquarters (country)",
  employee_range: "Employees",
  founded_year: "Founded",
};
