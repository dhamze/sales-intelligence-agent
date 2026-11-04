import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";
import { z } from "zod";

import { api, unwrap, type Schemas } from "@/lib/api/client";

export type Company = Schemas["CompanyOut"];
export type CompanyCreate = Schemas["CompanyCreate"];
export type CompanyUpdate = Schemas["CompanyUpdate"];

export const SIZE_BUCKETS = {
  "1-10": { label: "1–10 employees", min: 1, max: 10 },
  "11-50": { label: "11–50 employees", min: 11, max: 50 },
  "51-200": { label: "51–200 employees", min: 51, max: 200 },
  "201-1000": { label: "201–1,000 employees", min: 201, max: 1000 },
  "1001+": { label: "1,001+ employees", min: 1001, max: undefined },
} as const;
type SizeBucket = keyof typeof SIZE_BUCKETS;

const SORTS = ["name", "-name", "created_at", "-created_at", "relevance"] as const;
export type CompanySort = (typeof SORTS)[number];

/** Filters live in the URL (shareable, back button works); this validates them. */
export const companySearchSchema = z.object({
  q: z.string().optional(),
  industry: z.array(z.string()).optional(),
  country: z.array(z.string()).optional(),
  size: z.enum(Object.keys(SIZE_BUCKETS) as [SizeBucket, ...SizeBucket[]]).optional(),
  sort: z.enum(SORTS).optional(),
});
export type CompanySearch = z.infer<typeof companySearchSchema>;

export function hasFilters(search: CompanySearch): boolean {
  return Boolean(search.q || search.industry?.length || search.country?.length || search.size);
}

const PAGE_SIZE = 50;

export const companyKeys = {
  all: ["companies"] as const,
  list: (search: CompanySearch) => ["companies", "list", search] as const,
  detail: (id: string) => ["companies", "detail", id] as const,
  facets: ["companies", "facets"] as const,
};

export function companiesQuery(search: CompanySearch) {
  const size = search.size ? SIZE_BUCKETS[search.size] : undefined;
  return infiniteQueryOptions({
    queryKey: companyKeys.list(search),
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        api.GET("/companies", {
          signal,
          params: {
            query: {
              q: search.q,
              industry: search.industry,
              country: search.country,
              employees_min: size?.min,
              employees_max: size?.max,
              sort: search.sort,
              limit: PAGE_SIZE,
              cursor: pageParam,
            },
          },
        }),
      ),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
}

export function companyQuery(id: string) {
  return queryOptions({
    queryKey: companyKeys.detail(id),
    queryFn: ({ signal }) =>
      unwrap(api.GET("/companies/{company_id}", { signal, params: { path: { company_id: id } } })),
  });
}

export const facetsQuery = queryOptions({
  queryKey: companyKeys.facets,
  queryFn: ({ signal }) => unwrap(api.GET("/companies/facets", { signal })),
  staleTime: 5 * 60_000,
});

/** Few-results search, e.g. for the company picker. */
export function companySearchQuery(q: string) {
  return queryOptions({
    queryKey: ["companies", "picker", q],
    queryFn: ({ signal }) =>
      unwrap(api.GET("/companies", { signal, params: { query: { q: q || undefined, limit: 8 } } })),
  });
}

export function createCompany(body: CompanyCreate): Promise<Company> {
  return unwrap(api.POST("/companies", { body }));
}

export function updateCompany(id: string, body: CompanyUpdate): Promise<Company> {
  return unwrap(
    api.PATCH("/companies/{company_id}", { params: { path: { company_id: id } }, body }),
  );
}

export async function deleteCompany(id: string): Promise<void> {
  await unwrap(api.DELETE("/companies/{company_id}", { params: { path: { company_id: id } } }));
}
