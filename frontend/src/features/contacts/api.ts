import { infiniteQueryOptions } from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "@/lib/api/client";

export type Contact = Schemas["ContactOut"];
export type ContactCreate = Schemas["ContactCreate"];
export type ContactUpdate = Schemas["ContactUpdate"];

const PAGE_SIZE = 50;

export interface ContactFilters {
  q?: string | undefined;
  companyId?: string | undefined;
}

export const contactKeys = {
  all: ["contacts"] as const,
  list: (filters: ContactFilters) => ["contacts", "list", filters] as const,
};

export function contactsQuery(filters: ContactFilters) {
  return infiniteQueryOptions({
    queryKey: contactKeys.list(filters),
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        api.GET("/contacts", {
          signal,
          params: {
            query: {
              q: filters.q,
              company_id: filters.companyId,
              sort: filters.q ? undefined : "full_name",
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

export function createContact(body: ContactCreate): Promise<Contact> {
  return unwrap(api.POST("/contacts", { body }));
}

export function updateContact(id: string, body: ContactUpdate): Promise<Contact> {
  return unwrap(
    api.PATCH("/contacts/{contact_id}", { params: { path: { contact_id: id } }, body }),
  );
}

export async function deleteContact(id: string): Promise<void> {
  await unwrap(api.DELETE("/contacts/{contact_id}", { params: { path: { contact_id: id } } }));
}
