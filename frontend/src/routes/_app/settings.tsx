import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/overlays";
import {
  Alert,
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  NativeSelect,
  PageHeader,
  Skeleton,
} from "@/components/ui/primitives";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { hasRole, meQuery, type Me, type Role } from "@/features/auth/api";
import {
  changeRole,
  membersQuery,
  removeMember,
  renameOrganization,
  type Member,
} from "@/features/organization/api";
import { assignableRoles, canRemove } from "@/features/organization/policy";
import { AiUsageCard } from "@/features/insights/ai-usage-card";
import { IcpBuilder } from "@/features/scoring/icp-builder";
import { ApiError, errorMessage } from "@/lib/api/client";
import { handleSubmitError } from "@/lib/forms";
import { formatDate } from "@/lib/utils";

export const Route = createFileRoute("/_app/settings")({
  component: SettingsPage,
});

function SettingsPage() {
  const { data: me } = useSuspenseQuery(meQuery);
  if (!me?.active_organization || !me.role) return null; // layout shows the "no org" state
  return (
    <>
      <PageHeader
        title="Settings"
        description="Your organization, who has access to it, and your ideal customer."
      />
      <div className="grid gap-6">
        <OrganizationCard me={me} />
        <IcpBuilder canEdit={hasRole(me, "admin")} />
        <MembersCard me={me} />
        <AiUsageCard />
      </div>
    </>
  );
}

const nameSchema = z.object({ name: z.string().trim().min(1, "Enter a name.").max(100) });

function OrganizationCard({ me }: { me: Me }) {
  const queryClient = useQueryClient();
  const canEdit = hasRole(me, "admin");
  const form = useForm<z.infer<typeof nameSchema>>({
    resolver: zodResolver(nameSchema),
    defaultValues: { name: me.active_organization?.name ?? "" },
  });
  const save = useMutation({
    mutationFn: (values: { name: string }) => renameOrganization(values.name),
    onSuccess: async (organization) => {
      form.reset({ name: organization.name });
      await queryClient.invalidateQueries({ queryKey: meQuery.queryKey });
      toast.success("Organization renamed.");
    },
    onError: (error) => {
      handleSubmitError(error, form.setError, ["name"]);
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Organization</CardTitle>
        <CardDescription>
          {canEdit ? "The name everyone in your team sees." : "Only admins can rename it."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={(e) =>
            void form.handleSubmit((v) => {
              save.mutate(v);
            })(e)
          }
          className="flex max-w-xl flex-wrap items-end gap-3"
          noValidate
        >
          <div className="min-w-60 flex-1">
            <FormField label="Name" error={form.formState.errors.name?.message}>
              <Input disabled={!canEdit} {...form.register("name")} />
            </FormField>
          </div>
          {canEdit && (
            <Button type="submit" disabled={!form.formState.isDirty || save.isPending}>
              {save.isPending ? "Saving…" : "Save"}
            </Button>
          )}
        </form>
      </CardContent>
    </Card>
  );
}

const ROLE_LABEL: Record<Role, string> = { owner: "Owner", admin: "Admin", member: "Member" };

function MembersCard({ me }: { me: Me }) {
  const members = useQuery(membersQuery);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const actor = me.role ?? "member";

  const onFailure = (error: Error) => {
    toast.error(
      error instanceof ApiError && error.code === "last_owner"
        ? "An organization needs at least one owner. Make someone else an owner first."
        : errorMessage(error),
    );
  };

  const updateRole = useMutation({
    mutationFn: ({ member, role }: { member: Member; role: Role }) =>
      changeRole(member.user_id, role),
    onSuccess: async (_, { member }) => {
      await queryClient.invalidateQueries({ queryKey: membersQuery.queryKey });
      if (member.user_id === me.user.id) {
        await queryClient.invalidateQueries({ queryKey: meQuery.queryKey });
      }
      toast.success("Role updated.");
    },
    onError: onFailure,
  });

  const remove = useMutation({
    mutationFn: (member: Member) => removeMember(member.user_id),
    onSuccess: async (_, member) => {
      if (member.user_id === me.user.id) {
        queryClient.clear(); // we just lost access to this organization's data
        await navigate({ to: "/companies" });
        toast.success(`You left ${me.active_organization?.name ?? "the organization"}.`);
        return;
      }
      await queryClient.invalidateQueries({ queryKey: membersQuery.queryKey });
      toast.success(`${member.name} was removed.`);
    },
    onError: onFailure,
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Members</CardTitle>
        <CardDescription>
          Owners and admins manage members. Inviting new people arrives with email support.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {members.isPending ? (
          <Skeleton className="h-32" />
        ) : members.isError ? (
          <Alert tone="danger">{errorMessage(members.error)}</Alert>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Name</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Joined</TableHead>
                <TableHead className="text-right">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {members.data.map((member) => {
                const isSelf = member.user_id === me.user.id;
                const roles = assignableRoles(actor, member.role);
                return (
                  <TableRow key={member.user_id}>
                    <TableCell>
                      <span className="font-medium">{member.name}</span>
                      {isSelf && (
                        <Badge tone="primary" className="ml-2">
                          You
                        </Badge>
                      )}
                      <div className="text-xs text-muted-foreground">{member.email}</div>
                    </TableCell>
                    <TableCell>
                      {roles.length > 0 ? (
                        <NativeSelect
                          aria-label={`Role of ${member.name}`}
                          className="w-36"
                          value={member.role}
                          disabled={updateRole.isPending}
                          onChange={(e) => {
                            updateRole.mutate({ member, role: e.target.value as Role });
                          }}
                        >
                          {roles.map((role) => (
                            <option key={role} value={role}>
                              {ROLE_LABEL[role]}
                            </option>
                          ))}
                        </NativeSelect>
                      ) : (
                        ROLE_LABEL[member.role]
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDate(member.joined_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      {canRemove(actor, member.role, isSelf) && (
                        <ConfirmDialog
                          trigger={
                            <Button variant="ghost" size="sm" className="text-destructive">
                              {isSelf ? "Leave" : "Remove"}
                            </Button>
                          }
                          title={isSelf ? "Leave this organization?" : `Remove ${member.name}?`}
                          description={
                            isSelf
                              ? "You will lose access to its companies and contacts."
                              : `${member.name} will lose access immediately.`
                          }
                          confirmLabel={isSelf ? "Leave" : "Remove"}
                          pending={remove.isPending}
                          onConfirm={() => {
                            remove.mutate(member);
                          }}
                        />
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
