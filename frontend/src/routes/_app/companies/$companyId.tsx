import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { ArrowLeft, ExternalLink, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ConfirmDialog, FormDialog } from "@/components/ui/overlays";
import {
  Alert,
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Skeleton,
} from "@/components/ui/primitives";
import { hasRole, meQuery } from "@/features/auth/api";
import { companyKeys, companyQuery, deleteCompany } from "@/features/companies/api";
import { CompanyForm } from "@/features/companies/company-form";
import { ContactsTable } from "@/features/contacts/contacts-table";
import { AiProfileCard } from "@/features/enrichment/ai-profile-card";
import { BriefCard } from "@/features/insights/brief-card";
import { IcpFitCard } from "@/features/scoring/icp-fit-card";
import { TierBadge } from "@/features/scoring/tier-badge";
import { ContactFormDialog } from "@/features/contacts/contact-form";
import { ApiError, errorMessage } from "@/lib/api/client";
import { formatDateTime, formatNumber, formatValue } from "@/lib/utils";

export const Route = createFileRoute("/_app/companies/$companyId")({
  component: CompanyPage,
});

function CompanyPage() {
  const { companyId } = Route.useParams();
  const company = useQuery(companyQuery(companyId));
  const { data: me } = useSuspenseQuery(meQuery);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [editing, setEditing] = useState(false);
  const [addingContact, setAddingContact] = useState(false);

  const remove = useMutation({
    mutationFn: () => deleteCompany(companyId),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: companyKeys.detail(companyId) });
      await queryClient.invalidateQueries({ queryKey: companyKeys.all });
      toast.success("Company deleted.");
      await navigate({ to: "/companies" });
    },
    onError: (error) => {
      toast.error(errorMessage(error));
    },
  });

  const back = (
    <Link
      to="/companies"
      className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="size-4" aria-hidden />
      All companies
    </Link>
  );

  if (company.isPending) {
    return (
      <>
        {back}
        <Skeleton className="mb-6 h-9 w-72" />
        <Skeleton className="h-64" />
      </>
    );
  }
  if (company.isError) {
    const notFound = company.error instanceof ApiError && company.error.status === 404;
    return (
      <>
        {back}
        <Alert tone="danger">
          {notFound ? "This company doesn't exist or was deleted." : errorMessage(company.error)}
        </Alert>
      </>
    );
  }

  const c = company.data;
  const details: [string, React.ReactNode][] = [
    ["Domain", c.domain ?? "—"],
    [
      "Website",
      c.website ? (
        <a
          href={c.website}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-primary hover:underline"
        >
          {c.website.replace(/^https?:\/\//, "").replace(/\/$/, "")}
          <ExternalLink className="size-3" aria-hidden />
        </a>
      ) : (
        "—"
      ),
    ],
    ["Industry", c.industry ?? "—"],
    ["Employees", formatNumber(c.employee_count)],
    ["Location", [c.city, c.country].filter(Boolean).join(", ") || "—"],
    ["Source", <Badge key="s">{c.source === "import" ? "CSV import" : "Added manually"}</Badge>],
    ["Added", formatDateTime(c.created_at)],
    ["Last updated", formatDateTime(c.updated_at)],
  ];
  const attributes = Object.entries(c.attributes);

  return (
    <>
      {back}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-3 text-2xl font-semibold tracking-tight">
            {c.name}
            {c.icp_tier && c.icp_score !== null && (
              <TierBadge tier={c.icp_tier} score={c.icp_score} />
            )}
          </h1>
          {c.domain && <p className="mt-1 text-sm text-muted-foreground">{c.domain}</p>}
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => {
              setEditing(true);
            }}
          >
            <Pencil aria-hidden />
            Edit
          </Button>
          {hasRole(me, "admin") && (
            <ConfirmDialog
              trigger={
                <Button variant="outline" className="text-destructive">
                  <Trash2 aria-hidden />
                  Delete
                </Button>
              }
              title={`Delete ${c.name}?`}
              description="The company is removed permanently. Its contacts are kept, without a company."
              confirmLabel="Delete company"
              pending={remove.isPending}
              onConfirm={() => {
                remove.mutate();
              }}
            />
          )}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Details</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
              {details.map(([label, value]) => (
                <div key={label}>
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {label}
                  </dt>
                  <dd className="mt-1 text-sm">{value}</dd>
                </div>
              ))}
            </dl>
            {c.description && (
              <p className="mt-6 whitespace-pre-line border-t pt-4 text-sm">{c.description}</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Other fields</CardTitle>
          </CardHeader>
          <CardContent>
            {attributes.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Extra columns from imported files appear here.
              </p>
            ) : (
              <dl className="grid gap-3">
                {attributes.map(([key, value]) => (
                  <div key={key}>
                    <dt className="text-xs text-muted-foreground">{key}</dt>
                    <dd className="text-sm">{formatValue(value)}</dd>
                  </div>
                ))}
              </dl>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="mt-6">
        <BriefCard companyId={c.id} />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <AiProfileCard companyId={c.id} />
        </div>
        <IcpFitCard companyId={c.id} />
      </div>

      <section className="mt-8">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Contacts</h2>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setAddingContact(true);
            }}
          >
            Add contact
          </Button>
        </div>
        <ContactsTable companyId={c.id} hideCompanyColumn />
      </section>

      <FormDialog open={editing} onOpenChange={setEditing} title={`Edit ${c.name}`}>
        <CompanyForm
          company={c}
          onSaved={() => {
            setEditing(false);
          }}
          onCancel={() => {
            setEditing(false);
          }}
        />
      </FormDialog>
      <ContactFormDialog
        open={addingContact}
        onOpenChange={setAddingContact}
        defaultCompany={{ id: c.id, name: c.name }}
      />
    </>
  );
}
