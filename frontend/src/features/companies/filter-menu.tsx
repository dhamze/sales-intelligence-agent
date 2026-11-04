import { ChevronDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/overlays";

/** A "pick any of these values" filter, showing how many records have each value (if known). */
export function FilterMenu({
  label,
  options,
  selected,
  onChange,
}: {
  label: string;
  options: { value: string; count?: number; label?: React.ReactNode }[];
  selected: string[];
  onChange: (values: string[]) => void;
}) {
  function toggle(value: string, checked: boolean) {
    onChange(checked ? [...selected, value] : selected.filter((v) => v !== value));
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" className={selected.length ? "border-primary/60" : ""}>
          {label}
          {selected.length > 0 && (
            <span className="rounded-full bg-primary px-1.5 text-xs text-primary-foreground">
              {selected.length}
            </span>
          )}
          <ChevronDown aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-h-80 overflow-y-auto">
        {options.length === 0 && <DropdownMenuLabel>No values yet</DropdownMenuLabel>}
        {options.map(({ value, count, label: optionLabel }) => (
          <DropdownMenuCheckboxItem
            key={value}
            checked={selected.includes(value)}
            onCheckedChange={(checked) => {
              toggle(value, checked);
            }}
            onSelect={(e) => {
              e.preventDefault(); // keep the menu open to pick several values
            }}
          >
            <span className="flex-1 truncate">{optionLabel ?? value}</span>
            {count !== undefined && <span className="text-xs text-muted-foreground">{count}</span>}
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
