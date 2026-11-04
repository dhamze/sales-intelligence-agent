import { queryOptions, type QueryClient } from "@tanstack/react-query";

import { api, ApiError, unwrap, type Schemas } from "@/lib/api/client";

export type Me = Schemas["MeResponse"];
export type Role = Schemas["Role"];

/** The current user, or null when not logged in (a 401 is an answer here, not an error). */
export const meQuery = queryOptions({
  queryKey: ["me"],
  queryFn: async (): Promise<Me | null> => {
    try {
      return await unwrap(api.GET("/auth/me"));
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return null;
      throw error;
    }
  },
  staleTime: 60_000,
});

export function login(body: Schemas["LoginRequest"]): Promise<Me> {
  return unwrap(api.POST("/auth/login", { body }));
}

export function signup(body: Schemas["SignupRequest"]): Promise<Me> {
  return unwrap(api.POST("/auth/signup", { body }));
}

export async function logout(): Promise<void> {
  await unwrap(api.POST("/auth/logout"));
}

export function switchOrganization(organizationId: string): Promise<Me> {
  return unwrap(
    api.PUT("/auth/session/organization", { body: { organization_id: organizationId } }),
  );
}

/** After login/logout/org switch every cached query may belong to someone else: start clean. */
export function resetSession(queryClient: QueryClient, me: Me | null): void {
  queryClient.clear();
  queryClient.setQueryData(meQuery.queryKey, me);
}

const RANK: Record<Role, number> = { member: 0, admin: 1, owner: 2 };

export function hasRole(me: Me | null | undefined, minimum: Role): boolean {
  return me?.role != null && RANK[me.role] >= RANK[minimum];
}
