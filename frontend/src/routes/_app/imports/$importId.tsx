import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { AlertTriangle, ArrowLeft, CheckCircle2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Alert,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
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
import { companyKeys } from "@/features/companies/api";
import { contactKeys } from "@/features/contacts/api";
import {
  commitImport,
  FIELD_LABELS,
  importKeys,
  importQuery,
  orderedMapping,
  previewQuery,
  type ImportOut,
  type Mapping,
} from "@/features/imports/api";
import { ApiError, errorMessage } from "@/lib/api/client";
import { formatDateTime, formatNumber } from "@/lib/utils";

export const Route = createFileRoute("/_app/imports/$importId")({
  component: ImportPage,
});

function ImportPage() {
  const { importId } = Route.useParams();
  const record = useQuery(importQuery(importId));

  return (
    <>
      <Link
        to="/imports"
        className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        All imports
      </Link>
      {record.isPending ? (
        <Skeleton className="h-64" />
      ) : record.isError ? (
        <Alert tone="danger">{errorMessage(record.error)}</Alert>
      ) : record.data.status === "completed" ? (
        <ImportResult result={record.data} />
      ) : (
        <ImportReview importId={importId} filename={record.data.filename} />
      )}
    </>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "warn" }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
        <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone ? "text-warning" : ""}`}>
          {formatNumber(value)}
        </p>
      </CardContent>
    </Card>
  );
}

function ImportReview({ importId, filename }: { importId: string; filename: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  // null = the mapping detected at upload; an object = the user's edited mapping
  const [mapping, setMapping] = useState<Mapping | null>(null);
  const preview = useQuery(previewQuery(importId, mapping));

  const commit = useMutation({
    mutationFn: (finalMapping: Mapping) => commitImport(importId, finalMapping),
    onSuccess: async (result) => {
      queryClient.setQueryData(importKeys.detail(importId), result);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: importKeys.list }),
        queryClient.invalidateQueries({ queryKey: companyKeys.all }),
        queryClient.invalidateQueries({ queryKey: contactKeys.all }),
      ]);
      toast.success("Import complete.");
    },
    onError: (error) => {
      toast.error(errorMessage(error));
    },
  });

  if (preview.isPending) return <Skeleton className="h-64" />;
  if (preview.isError) {
    const expired = preview.error instanceof ApiError && preview.error.code === "import_expired";
    return (
      <Alert tone="danger">
        {expired ? "This preview has expired (after 24 hours). " : errorMessage(preview.error)}
        {expired && (
          <Link to="/imports/new" className="font-medium underline">
            Upload the file again
          </Link>
        )}
      </Alert>
    );
  }

  const p = preview.data;
  // The user's edits are the source of truth. The preview is refetched after every change and
  // is briefly stale meanwhile, so the mapping must never be rebuilt from preview data
  // (doing so silently undid earlier edits when several columns were changed quickly).
  const current: Mapping = mapping ?? Object.fromEntries(orderedMapping(p));
  const columns = p.headers.map((header): [string, string | null] => [
    header,
    current[header] ?? null,
  ]);
  const noun = p.entity_type === "companies" ? "companies" : "contacts";
  const skipped = p.invalid_count + p.duplicate_count;

  function setTarget(header: string, target: string | null) {
    setMapping((previous) => ({
      ...(previous ?? Object.fromEntries(orderedMapping(p))),
      [header]: target,
    }));
  }

  return (
    <>
      <PageHeader
        title={`Review ${filename}`}
        description="Step 2 of 2: check how columns are matched, then import. Nothing has been saved yet."
      />
      <div className="mb-6 grid gap-3 sm:grid-cols-4" aria-live="polite">
        <Stat label="Rows in file" value={p.row_count} />
        <Stat label={`Ready to import`} value={p.valid_count} />
        <Stat label="Match existing (merge)" value={p.existing_matches} />
        <Stat label="Will be skipped" value={skipped} tone={skipped ? "warn" : undefined} />
      </div>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Columns</CardTitle>
          <p className="text-sm text-muted-foreground">
            Each column in your file goes into a field. Existing {noun} only get their empty fields
            filled in; nothing is overwritten.
          </p>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="py-2 pr-4 font-medium">Column in your file</th>
                <th className="py-2 pr-4 font-medium">Example values</th>
                <th className="py-2 font-medium">Import as</th>
              </tr>
            </thead>
            <tbody>
              {columns.map(([header, target]) => {
                const usedElsewhere = new Set(
                  columns
                    .filter(([h, t]) => h !== header && t && t !== "attributes")
                    .map(([, t]) => t),
                );
                const examples = p.sample_rows
                  .map((row) => row[header])
                  .filter(Boolean)
                  .slice(0, 3);
                return (
                  <tr key={header} className="border-b last:border-0">
                    <td className="py-2 pr-4 font-medium">{header}</td>
                    <td className="max-w-xs truncate py-2 pr-4 text-muted-foreground">
                      {examples.join(" · ") || "—"}
                    </td>
                    <td className="py-2">
                      <NativeSelect
                        aria-label={`Import column ${header} as`}
                        value={target ?? ""}
                        className="min-w-52"
                        onChange={(e) => {
                          setTarget(header, e.target.value || null);
                        }}
                      >
                        <option value="">Don't import</option>
                        {p.available_fields.map((field) => (
                          <option key={field} value={field} disabled={usedElsewhere.has(field)}>
                            {FIELD_LABELS[field] ?? field}
                          </option>
                        ))}
                      </NativeSelect>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {p.errors.length > 0 && <ProblemRows errors={p.errors} total={skipped} completed={false} />}

      <div className="sticky bottom-0 -mx-4 mt-6 flex items-center justify-end gap-2 border-t bg-background/95 px-4 py-4 backdrop-blur md:-mx-8 md:px-8">
        {preview.isFetching && <span className="text-sm text-muted-foreground">Updating…</span>}
        <Button
          variant="outline"
          onClick={() => void navigate({ to: "/imports" })}
          disabled={commit.isPending}
        >
          Not now
        </Button>
        <Button
          disabled={p.valid_count === 0 || preview.isFetching || commit.isPending}
          onClick={() => {
            commit.mutate(current);
          }}
        >
          {commit.isPending
            ? "Importing…"
            : `Import ${formatNumber(p.valid_count)} ${p.valid_count === 1 ? noun.slice(0, -1) : noun}`}
        </Button>
      </div>
    </>
  );
}

function ProblemRows({
  errors,
  total,
  completed,
}: {
  errors: { row: number; field: string | null; message: string }[];
  total: number;
  completed: boolean;
}) {
  return (
    <section className="mt-6">
      <h2 className="mb-1 flex items-center gap-2 text-lg font-semibold">
        <AlertTriangle className="size-5 text-warning" aria-hidden />
        {completed ? "Rows that were skipped" : "Rows that will be skipped"}
      </h2>
      <p className="mb-3 text-sm text-muted-foreground">
        Fix these in your file and import it again if you need them.
        {total > errors.length && ` Showing the first ${errors.length} of ${total}.`}
      </p>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="w-24">Line</TableHead>
            <TableHead className="w-48">Field</TableHead>
            <TableHead>Problem</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {errors.map((e, i) => (
            <TableRow key={`${e.row}-${e.field ?? ""}-${i}`}>
              <TableCell className="tabular-nums">{e.row}</TableCell>
              <TableCell>{e.field ? (FIELD_LABELS[e.field] ?? e.field) : "—"}</TableCell>
              <TableCell>{e.message}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </section>
  );
}

function ImportResult({ result }: { result: ImportOut }) {
  const noun = result.entity_type === "companies" ? "companies" : "contacts";
  const skipped = result.invalid_count + result.duplicate_count;
  return (
    <>
      <PageHeader
        title={result.filename}
        description={`Imported ${result.completed_at ? formatDateTime(result.completed_at) : ""}`}
        actions={
          <Button asChild>
            <Link to={result.entity_type === "companies" ? "/companies" : "/contacts"}>
              View {noun}
            </Link>
          </Button>
        }
      />
      <Alert tone="success" className="mb-6 flex items-center gap-2">
        <CheckCircle2 className="size-4 text-success" aria-hidden />
        Import complete.
      </Alert>
      <div className="mb-6 grid gap-3 sm:grid-cols-4">
        <Stat label={`New ${noun}`} value={result.created_count} />
        <Stat label="Existing, filled in" value={result.updated_count} />
        <Stat label="Already up to date" value={result.unchanged_count} />
        <Stat label="Skipped" value={skipped} tone={skipped ? "warn" : undefined} />
      </div>
      {result.errors.length > 0 && <ProblemRows errors={result.errors} total={skipped} completed />}
    </>
  );
}
