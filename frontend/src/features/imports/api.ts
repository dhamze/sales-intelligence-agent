import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "@/lib/api/client";

export type ImportOut = Schemas["ImportOut"];
export type ImportPreview = Schemas["ImportPreview"];
export type EntityType = Schemas["EntityType"];
export type Mapping = Record<string, string | null>;

export const MAX_FILE_MB = 5;

export const importKeys = {
  all: ["imports"] as const,
  list: ["imports", "list"] as const,
  detail: (id: string) => ["imports", "detail", id] as const,
  preview: (id: string, mapping: Mapping | null) => ["imports", "preview", id, mapping] as const,
};

/** Upload a CSV. Returns the preview; nothing is imported until `commitImport`. */
export function uploadImport(file: File, entityType: EntityType): Promise<ImportPreview> {
  return unwrap(
    api.POST("/imports", {
      // The generated type describes the form fields; the browser sends real multipart data.
      body: { file: file.name, entity_type: entityType },
      bodySerializer: () => {
        const form = new FormData();
        form.append("file", file);
        form.append("entity_type", entityType);
        return form;
      },
    }),
  );
}

/** Preview of a pending import; with `mapping`, shows what that column mapping would do. */
export function previewQuery(id: string, mapping: Mapping | null) {
  return queryOptions({
    queryKey: importKeys.preview(id, mapping),
    queryFn: ({ signal }) =>
      unwrap(
        api.POST("/imports/{import_id}/preview", {
          signal,
          params: { path: { import_id: id } },
          body: { mapping },
        }),
      ),
    placeholderData: (previous) => previous, // keep the table on screen while recomputing
  });
}

export function importQuery(id: string) {
  return queryOptions({
    queryKey: importKeys.detail(id),
    queryFn: ({ signal }) =>
      unwrap(api.GET("/imports/{import_id}", { signal, params: { path: { import_id: id } } })),
  });
}

export const importsQuery = infiniteQueryOptions({
  queryKey: importKeys.list,
  queryFn: ({ pageParam, signal }) =>
    unwrap(api.GET("/imports", { signal, params: { query: { limit: 25, cursor: pageParam } } })),
  initialPageParam: undefined as string | undefined,
  getNextPageParam: (page) => page.next_cursor ?? undefined,
});

export function commitImport(id: string, mapping: Mapping): Promise<ImportOut> {
  return unwrap(
    api.POST("/imports/{import_id}/commit", {
      params: { path: { import_id: id } },
      body: { mapping },
    }),
  );
}

export const FIELD_LABELS: Record<string, string> = {
  name: "Name",
  domain: "Domain",
  website: "Website",
  industry: "Industry",
  employee_count: "Employees",
  country: "Country",
  city: "City",
  description: "Description",
  first_name: "First name",
  last_name: "Last name",
  full_name: "Full name",
  email: "Email",
  title: "Job title",
  phone: "Phone",
  linkedin_url: "LinkedIn URL",
  company_domain: "Company domain / website",
  attributes: "Keep as extra field",
};

/** Columns in file order (JSON objects from the API don't guarantee key order). */
export function orderedMapping(preview: ImportPreview): [string, string | null][] {
  return preview.headers.map((header) => [header, preview.mapping[header] ?? null]);
}
