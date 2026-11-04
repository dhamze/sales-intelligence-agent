import { useId, type ReactElement, type ReactNode } from "react";
import { cloneElement } from "react";

import { Label } from "@/components/ui/primitives";

/**
 * Label + control + error message, wired together for accessibility: the label targets the
 * control, and the error is announced via aria-describedby / aria-invalid.
 */
export function FormField({
  label,
  error,
  hint,
  children,
}: {
  label: string;
  error?: string | undefined;
  hint?: ReactNode;
  children: ReactElement<Record<string, unknown>>;
}) {
  const id = useId();
  const messageId = `${id}-message`;
  const control = cloneElement(children, {
    id,
    "aria-invalid": error ? true : undefined,
    "aria-describedby": error || hint ? messageId : undefined,
  });
  return (
    <div className="grid content-start gap-2">
      <Label htmlFor={id}>{label}</Label>
      {control}
      {(error || hint) && (
        <div id={messageId} className="grid gap-1">
          {error && <p className="text-sm text-destructive">{error}</p>}
          {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
        </div>
      )}
    </div>
  );
}
