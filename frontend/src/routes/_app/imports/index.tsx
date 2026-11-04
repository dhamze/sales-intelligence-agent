import { useInfiniteQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { FileUp, History } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Alert, Badge, EmptyState, PageHeader, Skeleton } from "@/components/ui/primitives";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { importsQuery } from "@/features/imports/api";
import { errorMessage } from "@/lib/api/client";
import { formatDateTime, formatNumber } from "@/lib/utils";

export const Route = createFileRoute("/_app/imports/")({
  component: ImportsPage,
});

function ImportsPage() {
  const imports = useInfiniteQuery(importsQuery);
  const rows = imports.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <>
      <PageHeader
        title="Imports"
        description="Bring in companies or contacts from a CSV file. You review every import before anything is saved."
        actions={
          <Button asChild>
            <Link to="/imports/new">
              <FileUp aria-hidden />
              New import
            </Link>
          </Button>
        }
      />
      {imports.isError ? (
        <Alert tone="danger">{errorMessage(imports.error)}</Alert>
      ) : imports.isPending ? (
        <Skeleton className="h-48" />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<History />}
          title="No imports yet"
          description="Export a list from your CRM or spreadsheet as CSV and upload it here."
          action={
            <Button asChild>
              <Link to="/imports/new">Start an import</Link>
            </Button>
          }
        />
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>File</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Rows</TableHead>
                <TableHead className="text-right">Created</TableHead>
                <TableHead className="text-right">Updated</TableHead>
                <TableHead>Uploaded</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((item) => (
                <TableRow key={item.id}>
                  <TableCell>
                    <Link
                      to="/imports/$importId"
                      params={{ importId: item.id }}
                      className="font-medium hover:text-primary hover:underline"
                    >
                      {item.filename}
                    </Link>
                  </TableCell>
                  <TableCell className="capitalize">{item.entity_type}</TableCell>
                  <TableCell>
                    {item.status === "completed" ? (
                      <Badge tone="success">Completed</Badge>
                    ) : (
                      <Badge tone="warning">Awaiting review</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatNumber(item.row_count)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {item.status === "completed" ? formatNumber(item.created_count) : "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {item.status === "completed" ? formatNumber(item.updated_count) : "—"}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(item.created_at)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {imports.hasNextPage && (
            <div className="mt-4 flex justify-end">
              <Button
                variant="outline"
                onClick={() => void imports.fetchNextPage()}
                disabled={imports.isFetchingNextPage}
              >
                Load more
              </Button>
            </div>
          )}
        </>
      )}
    </>
  );
}
