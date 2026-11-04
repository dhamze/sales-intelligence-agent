import { useQuery } from "@tanstack/react-query";
import { Building2, X } from "lucide-react";
import { useId, useState } from "react";

import { Input } from "@/components/ui/primitives";
import { companySearchQuery } from "@/features/companies/api";
import { useDebouncedValue } from "@/lib/hooks";
import { cn } from "@/lib/utils";

export interface CompanyChoice {
  id: string;
  name: string;
}

/**
 * Search-as-you-type company selector (ARIA combobox pattern): type to search, arrow keys to
 * move, Enter to choose, Escape to close.
 */
export function CompanyPicker({
  value,
  onChange,
  id,
  ...aria
}: {
  value: CompanyChoice | null;
  onChange: (value: CompanyChoice | null) => void;
  id?: string;
  "aria-invalid"?: boolean;
  "aria-describedby"?: string;
}) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const listId = useId();
  const q = useDebouncedValue(text.trim(), 250);
  const results = useQuery({ ...companySearchQuery(q), enabled: open });
  const options = results.data?.items ?? [];

  if (value) {
    return (
      <div className="flex h-9 items-center justify-between rounded-md border border-input bg-card px-3 text-sm shadow-sm">
        <span className="flex items-center gap-2 truncate">
          <Building2 className="size-4 text-muted-foreground" aria-hidden />
          {value.name}
        </span>
        <button
          type="button"
          className="rounded p-0.5 text-muted-foreground hover:bg-muted"
          aria-label={`Remove company ${value.name}`}
          onClick={() => {
            onChange(null);
          }}
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
    );
  }

  function choose(index: number) {
    const option = options[index];
    if (!option) return;
    onChange({ id: option.id, name: option.name });
    setText("");
    setOpen(false);
  }

  return (
    <div className="relative">
      <Input
        id={id}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && options[active] ? `${listId}-${active}` : undefined}
        placeholder="Search companies…"
        autoComplete="off"
        value={text}
        {...aria}
        onChange={(e) => {
          setText(e.target.value);
          setActive(0);
          setOpen(true);
        }}
        onFocus={() => {
          setOpen(true);
        }}
        onBlur={() => {
          setOpen(false);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setOpen(true);
            setActive((i) => Math.min(i + 1, options.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((i) => Math.max(i - 1, 0));
          } else if (e.key === "Enter" && open && options.length > 0) {
            e.preventDefault();
            choose(active);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
      />
      {open && (
        <ul
          id={listId}
          role="listbox"
          className="absolute z-10 mt-1 max-h-60 w-full overflow-y-auto rounded-lg border bg-card p-1 shadow-lg"
        >
          {results.isPending ? (
            <li className="px-2 py-1.5 text-sm text-muted-foreground">Searching…</li>
          ) : options.length === 0 ? (
            <li className="px-2 py-1.5 text-sm text-muted-foreground">No companies found</li>
          ) : (
            options.map((company, index) => (
              <li
                key={company.id}
                id={`${listId}-${index}`}
                role="option"
                aria-selected={index === active}
                className={cn(
                  "cursor-pointer rounded-md px-2 py-1.5 text-sm",
                  index === active && "bg-muted",
                )}
                // mousedown (not click) fires before the input's blur closes the list
                onMouseDown={(e) => {
                  e.preventDefault();
                  choose(index);
                }}
                onMouseEnter={() => {
                  setActive(index);
                }}
              >
                <span className="font-medium">{company.name}</span>
                {company.domain && (
                  <span className="ml-2 text-xs text-muted-foreground">{company.domain}</span>
                )}
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
