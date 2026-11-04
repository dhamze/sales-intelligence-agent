import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Plus, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input, PageHeader } from "@/components/ui/primitives";
import { ContactFormDialog } from "@/features/contacts/contact-form";
import { ContactsTable } from "@/features/contacts/contacts-table";
import { useDebouncedValue } from "@/lib/hooks";

export const Route = createFileRoute("/_app/contacts/")({
  validateSearch: z.object({ q: z.string().optional() }),
  component: ContactsPage,
});

function ContactsPage() {
  const { q } = Route.useSearch();
  const navigate = useNavigate({ from: Route.fullPath });
  const [creating, setCreating] = useState(false);
  const [text, setText] = useState(q ?? "");
  const debounced = useDebouncedValue(text.trim(), 300);

  useEffect(() => {
    if (debounced !== (q ?? "")) {
      void navigate({ search: { q: debounced || undefined }, replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- react only to new debounced text
  }, [debounced]);

  return (
    <>
      <PageHeader
        title="Contacts"
        description="People at your accounts. Click a name to edit."
        actions={
          <Button
            onClick={() => {
              setCreating(true);
            }}
          >
            <Plus aria-hidden />
            New contact
          </Button>
        }
      />
      <div className="relative mb-4 max-w-md">
        <Search
          className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          type="search"
          aria-label="Search contacts"
          placeholder="Search by name or email…"
          className="pl-9"
          value={text}
          onChange={(e) => {
            setText(e.target.value);
          }}
        />
      </div>
      <ContactsTable q={q} />
      <ContactFormDialog open={creating} onOpenChange={setCreating} />
    </>
  );
}
