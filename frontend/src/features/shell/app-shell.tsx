import { useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import {
  Building2,
  Check,
  ChevronsUpDown,
  FileUp,
  LogOut,
  Monitor,
  Moon,
  Settings,
  Sun,
  Users,
} from "lucide-react";
import type { ReactNode } from "react";
import { toast } from "sonner";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/overlays";
import { logout, meQuery, resetSession, switchOrganization, type Me } from "@/features/auth/api";
import { errorMessage } from "@/lib/api/client";
import { useTheme, type Theme } from "@/lib/theme";

const NAV = [
  { to: "/companies", label: "Companies", icon: Building2 },
  { to: "/contacts", label: "Contacts", icon: Users },
  { to: "/imports", label: "Imports", icon: FileUp },
  { to: "/settings", label: "Settings", icon: Settings },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const { data: me } = useSuspenseQuery(meQuery);
  if (!me) return null; // the route guard redirects before this can happen
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="flex shrink-0 flex-col gap-4 border-b bg-card p-3 md:sticky md:top-0 md:h-screen md:w-60 md:border-b-0 md:border-r">
        <div className="flex items-center gap-2 px-2 pt-1 font-semibold">
          <img src="/favicon.svg" alt="" className="size-7" />
          Sales Intelligence
        </div>
        <OrganizationSwitcher me={me} />
        <nav aria-label="Main" className="flex gap-1 overflow-x-auto md:flex-col">
          {NAV.map(({ to, label, icon: Icon }) => (
            <Link
              key={to}
              to={to}
              className="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground [&_svg]:size-4"
              activeProps={{ className: "!bg-accent !text-accent-foreground font-medium" }}
            >
              <Icon aria-hidden />
              {label}
            </Link>
          ))}
        </nav>
        <div className="md:mt-auto">
          <UserMenu me={me} />
        </div>
      </aside>
      <main className="min-w-0 flex-1 p-4 md:p-8">
        <div className="mx-auto max-w-6xl">{children}</div>
      </main>
    </div>
  );
}

function OrganizationSwitcher({ me }: { me: Me }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  async function select(organizationId: string) {
    if (organizationId === me.active_organization?.id) return;
    try {
      resetSession(queryClient, await switchOrganization(organizationId));
      await navigate({ to: "/companies" });
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex w-full items-center justify-between gap-2 rounded-lg border bg-background px-3 py-2 text-left text-sm shadow-sm hover:bg-muted">
        <span className="min-w-0">
          <span className="block text-xs text-muted-foreground">Organization</span>
          <span className="block truncate font-medium">
            {me.active_organization?.name ?? "None selected"}
          </span>
        </span>
        <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-56">
        <DropdownMenuLabel>Switch organization</DropdownMenuLabel>
        {me.memberships.map(({ organization, role }) => (
          <DropdownMenuItem key={organization.id} onSelect={() => void select(organization.id)}>
            <Check
              aria-hidden
              className={organization.id === me.active_organization?.id ? "" : "invisible"}
            />
            <span className="flex-1 truncate">{organization.name}</span>
            <span className="text-xs capitalize text-muted-foreground">{role}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

const THEMES: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

function UserMenu({ me }: { me: Me }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [theme, setTheme] = useTheme();

  async function signOut() {
    try {
      await logout();
    } finally {
      resetSession(queryClient, null);
      await navigate({ to: "/login", search: {} });
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left text-sm hover:bg-muted">
        <span
          aria-hidden
          className="flex size-8 items-center justify-center rounded-full bg-accent text-xs font-semibold text-accent-foreground"
        >
          {me.user.name.slice(0, 2).toUpperCase()}
        </span>
        <span className="min-w-0">
          <span className="block truncate font-medium">{me.user.name}</span>
          <span className="block truncate text-xs text-muted-foreground">{me.user.email}</span>
        </span>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start" className="w-56">
        <DropdownMenuLabel>Theme</DropdownMenuLabel>
        {THEMES.map(({ value, label, icon: Icon }) => (
          <DropdownMenuItem
            key={value}
            onSelect={() => {
              setTheme(value);
            }}
          >
            <Icon aria-hidden />
            <span className="flex-1">{label}</span>
            {theme === value && <Check aria-hidden />}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void signOut()}>
          <LogOut aria-hidden />
          Log out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
