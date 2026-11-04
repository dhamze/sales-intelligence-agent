import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { ArrowLeft, Building2, FileSpreadsheet, UploadCloud, Users } from "lucide-react";
import { useId, useRef, useState, type DragEvent } from "react";

import { Button } from "@/components/ui/button";
import { Alert, Card, CardContent, PageHeader } from "@/components/ui/primitives";
import { importKeys, MAX_FILE_MB, uploadImport, type EntityType } from "@/features/imports/api";
import { errorMessage } from "@/lib/api/client";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/_app/imports/new")({
  component: NewImportPage,
});

const ENTITY_OPTIONS: { value: EntityType; title: string; text: string; icon: typeof Users }[] = [
  {
    value: "companies",
    title: "Companies",
    text: "Accounts: name, website, industry, size, location…",
    icon: Building2,
  },
  {
    value: "contacts",
    title: "Contacts",
    text: "People: name, email, title… linked to companies by domain",
    icon: Users,
  },
];

function NewImportPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const [entity, setEntity] = useState<EntityType>("companies");
  const [dragging, setDragging] = useState(false);
  const [clientError, setClientError] = useState<string>();

  const upload = useMutation({
    mutationFn: (file: File) => uploadImport(file, entity),
    onSuccess: async (preview) => {
      queryClient.setQueryData(importKeys.preview(preview.id, null), preview);
      await queryClient.invalidateQueries({ queryKey: importKeys.list });
      await navigate({ to: "/imports/$importId", params: { importId: preview.id } });
    },
  });

  function choose(file: File | undefined) {
    setClientError(undefined);
    upload.reset();
    if (!file) return;
    if (!/\.(csv|txt|tsv)$/i.test(file.name)) {
      setClientError("Choose a .csv file. In Excel or Google Sheets: File → Download → CSV.");
      return;
    }
    if (file.size > MAX_FILE_MB * 1024 * 1024) {
      setClientError(`This file is larger than ${MAX_FILE_MB} MB. Split it into smaller files.`);
      return;
    }
    upload.mutate(file);
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    choose(event.dataTransfer.files[0]);
  }

  const error = clientError ?? (upload.isError ? errorMessage(upload.error) : undefined);

  return (
    <>
      <Link
        to="/imports"
        className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        All imports
      </Link>
      <PageHeader
        title="New import"
        description="Step 1 of 2: choose what you're importing and upload the file."
      />

      <fieldset className="mb-6">
        <legend className="mb-3 text-sm font-medium">What does the file contain?</legend>
        <div className="grid gap-3 sm:grid-cols-2">
          {ENTITY_OPTIONS.map(({ value, title, text, icon: Icon }) => (
            <label
              key={value}
              className={cn(
                "flex cursor-pointer gap-3 rounded-xl border bg-card p-4 shadow-sm transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-ring",
                entity === value ? "border-primary ring-1 ring-primary" : "hover:bg-muted/50",
              )}
            >
              <input
                type="radio"
                name="entity"
                value={value}
                checked={entity === value}
                onChange={() => {
                  setEntity(value);
                }}
                className="sr-only"
              />
              <Icon className="mt-0.5 size-5 text-primary" aria-hidden />
              <span>
                <span className="block font-medium">{title}</span>
                <span className="block text-sm text-muted-foreground">{text}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <Card>
        <CardContent className="p-6">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => {
              setDragging(false);
            }}
            onDrop={onDrop}
            className={cn(
              "flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed px-6 py-12 text-center transition-colors",
              dragging ? "border-primary bg-accent/50" : "border-border",
            )}
          >
            {upload.isPending ? (
              <>
                <FileSpreadsheet className="size-10 animate-pulse text-primary" aria-hidden />
                <p className="font-medium">Reading your file…</p>
              </>
            ) : (
              <>
                <UploadCloud className="size-10 text-muted-foreground" aria-hidden />
                <div>
                  <p className="font-medium">Drop a CSV file here</p>
                  <p className="text-sm text-muted-foreground">
                    Up to {MAX_FILE_MB} MB and 10,000 rows. Excel exports work too.
                  </p>
                </div>
                <label htmlFor={inputId} className="sr-only">
                  Choose CSV file
                </label>
                <input
                  id={inputId}
                  ref={inputRef}
                  type="file"
                  accept=".csv,.tsv,.txt,text/csv"
                  className="sr-only"
                  onChange={(e) => {
                    choose(e.target.files?.[0]);
                    e.target.value = ""; // allow choosing the same file again
                  }}
                />
                <Button type="button" variant="outline" onClick={() => inputRef.current?.click()}>
                  Choose file
                </Button>
              </>
            )}
          </div>
          {error && (
            <Alert tone="danger" className="mt-4">
              {error}
            </Alert>
          )}
        </CardContent>
      </Card>
      <p className="mt-4 text-sm text-muted-foreground">
        Nothing is saved yet: you'll review the column mapping and any problems first.
      </p>
    </>
  );
}
