import { queryOptions } from "@tanstack/react-query";

import type { Role } from "@/features/auth/api";
import { api, unwrap, type Schemas } from "@/lib/api/client";

export type Member = Schemas["MemberOut"];

export const membersQuery = queryOptions({
  queryKey: ["organization", "members"],
  queryFn: ({ signal }) => unwrap(api.GET("/organizations/current/members", { signal })),
});

export function renameOrganization(name: string) {
  return unwrap(api.PATCH("/organizations/current", { body: { name } }));
}

export async function changeRole(userId: string, role: Role): Promise<void> {
  await unwrap(
    api.PATCH("/organizations/current/members/{user_id}", {
      params: { path: { user_id: userId } },
      body: { role },
    }),
  );
}

export async function removeMember(userId: string): Promise<void> {
  await unwrap(
    api.DELETE("/organizations/current/members/{user_id}", {
      params: { path: { user_id: userId } },
    }),
  );
}
