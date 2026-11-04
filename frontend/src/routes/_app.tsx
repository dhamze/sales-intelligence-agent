import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute, Outlet, redirect } from "@tanstack/react-router";
import { Building2 } from "lucide-react";

import { EmptyState } from "@/components/ui/primitives";
import { meQuery } from "@/features/auth/api";
import { AppShell } from "@/features/shell/app-shell";

/** Layout for every logged-in page. Not logged in -> login page, then back here afterwards. */
export const Route = createFileRoute("/_app")({
  beforeLoad: async ({ context, location }) => {
    const me = await context.queryClient.query({ ...meQuery, staleTime: "static" });
    if (!me) {
      throw redirect({ to: "/login", search: { redirect: location.href } });
    }
  },
  component: AppLayout,
});

function AppLayout() {
  const { data: me } = useSuspenseQuery(meQuery); // live: updates after an org switch
  return (
    <AppShell>
      {me?.active_organization ? (
        <Outlet />
      ) : (
        <EmptyState
          icon={<Building2 />}
          title="No organization selected"
          description={
            me && me.memberships.length > 0
              ? "Choose an organization from the switcher to continue."
              : "You're not a member of any organization. Ask an admin to add you."
          }
        />
      )}
    </AppShell>
  );
}
