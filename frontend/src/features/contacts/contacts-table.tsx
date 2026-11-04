import { useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Users } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Alert, EmptyState, Skeleton } from "@/components/ui/primitives";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { errorMessage } from "@/lib/api/client";
import { formatNumber } from "@/lib/utils";

import { contactsQuery, type Contact, type ContactFilters } from "./api";
import { ContactFormDialog } from "./contact-form";

export function ContactsTable({
  q,
  companyId,
  hideCompanyColumn = false,
}: ContactFilters & { hideCompanyColumn?: boolean }) {
  const contacts = useInfiniteQuery(contactsQuery({ q, companyId }));
  const [editing, setEditing] = useState<Contact>();
  const rows = contacts.data?.pages.flatMap((page) => page.items) ?? [];

  if (contacts.isError) return <Alert tone="danger">{errorMessage(contacts.error)}</Alert>;
  if (contacts.isPending) {
    return (
      <div className="grid gap-2 rounded-xl border bg-card p-4" aria-busy="true">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-10" />
        ))}
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<Users />}
        title={q ? "No contacts match your search" : "No contacts yet"}
        description={
          q ? "Try a different name or email." : "Add contacts, or import them from a CSV."
        }
      />
    );
  }

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Name</TableHead>
            <TableHead>Email</TableHead>
            {!hideCompanyColumn && <TableHead>Company</TableHead>}
            <TableHead>Phone</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((contact) => (
            <TableRow key={contact.id}>
              <TableCell>
                <button
                  type="button"
                  className="text-left font-medium hover:text-primary hover:underline"
                  onClick={() => {
                    setEditing(contact);
                  }}
                >
                  {contact.full_name || contact.email}
                </button>
                {contact.title && (
                  <div className="text-xs text-muted-foreground">{contact.title}</div>
                )}
              </TableCell>
              <TableCell>
                {contact.email ? (
                  <a href={`mailto:${contact.email}`} className="hover:underline">
                    {contact.email}
                  </a>
                ) : (
                  "—"
                )}
              </TableCell>
              {!hideCompanyColumn && (
                <TableCell>
                  {contact.company_id && contact.company_name ? (
                    <Link
                      to="/companies/$companyId"
                      params={{ companyId: contact.company_id }}
                      className="hover:underline"
                    >
                      {contact.company_name}
                    </Link>
                  ) : (
                    "—"
                  )}
                </TableCell>
              )}
              <TableCell className="tabular-nums">{contact.phone ?? "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
        <span>Showing {formatNumber(rows.length)}</span>
        {contacts.hasNextPage && (
          <Button
            variant="outline"
            onClick={() => void contacts.fetchNextPage()}
            disabled={contacts.isFetchingNextPage}
          >
            {contacts.isFetchingNextPage ? "Loading…" : "Load more"}
          </Button>
        )}
      </div>
      <ContactFormDialog
        open={editing !== undefined}
        onOpenChange={(open) => {
          if (!open) setEditing(undefined);
        }}
        contact={editing}
      />
    </>
  );
}
