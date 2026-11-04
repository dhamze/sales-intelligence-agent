import type { FieldValues, Path, UseFormSetError } from "react-hook-form";
import { toast } from "sonner";

import { ApiError, errorMessage } from "@/lib/api/client";

/**
 * Show a failed submission to the user: validation errors next to their fields (when the field
 * exists in this form), everything else as a toast.
 */
export function handleSubmitError<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  fields: readonly string[],
): void {
  if (error instanceof ApiError && error.status === 422) {
    const matched = error.fieldErrors.filter((e) => fields.includes(e.field));
    for (const { field, message } of matched) {
      setError(field as Path<T>, { type: "server", message });
    }
    if (matched.length > 0) return;
  }
  toast.error(errorMessage(error));
}
