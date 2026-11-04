import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api/client";
import { handleSubmitError } from "@/lib/forms";

import { companyKeys, createCompany, updateCompany, type Company } from "./api";

const optionalText = (max: number) => z.string().trim().max(max, `At most ${max} characters.`);

const formSchema = z.object({
  name: z.string().trim().min(1, "Enter the company name.").max(200),
  website: optionalText(2048),
  domain: optionalText(253),
  industry: optionalText(100),
  employee_count: z
    .string()
    .trim()
    .regex(/^\d*$/, "Enter a whole number.")
    .refine((v) => v === "" || Number(v) <= 10_000_000, "That number is too large."),
  country: optionalText(100),
  city: optionalText(100),
  description: optionalText(5000),
});
type FormValues = z.infer<typeof formSchema>;
const FIELDS = Object.keys(formSchema.shape);

function toFormValues(company?: Company): FormValues {
  return {
    name: company?.name ?? "",
    website: company?.website ?? "",
    domain: company?.domain ?? "",
    industry: company?.industry ?? "",
    employee_count: company?.employee_count?.toString() ?? "",
    country: company?.country ?? "",
    city: company?.city ?? "",
    description: company?.description ?? "",
  };
}

/** Empty inputs are sent as null, so clearing a field in the form clears it on the server. */
function toBody(values: FormValues) {
  const orNull = (v: string) => (v === "" ? null : v);
  return {
    name: values.name,
    website: orNull(values.website),
    domain: orNull(values.domain),
    industry: orNull(values.industry),
    employee_count: values.employee_count === "" ? null : Number(values.employee_count),
    country: orNull(values.country),
    city: orNull(values.city),
    description: orNull(values.description),
  };
}

export function CompanyForm({
  company,
  onSaved,
  onCancel,
}: {
  company?: Company;
  onSaved: (company: Company) => void;
  onCancel: () => void;
}) {
  const queryClient = useQueryClient();
  // ID of the existing company that already owns the entered domain (to link to it).
  const [takenBy, setTakenBy] = useState<string>();
  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: toFormValues(company),
  });

  const save = useMutation({
    mutationFn: (values: FormValues) =>
      company ? updateCompany(company.id, toBody(values)) : createCompany(toBody(values)),
    onSuccess: async (saved) => {
      queryClient.setQueryData(companyKeys.detail(saved.id), saved);
      await queryClient.invalidateQueries({ queryKey: companyKeys.all });
      toast.success(company ? "Company updated." : "Company created.");
      onSaved(saved);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "domain_taken") {
        setTakenBy(
          (error.details[0] as { existing_company_id?: string } | undefined)?.existing_company_id,
        );
        form.setError("domain", { message: "A company with this domain already exists." });
        return;
      }
      handleSubmitError(error, form.setError, FIELDS);
    },
  });

  const { errors } = form.formState;

  return (
    <form
      onSubmit={(e) =>
        void form.handleSubmit((values) => {
          setTakenBy(undefined);
          save.mutate(values);
        })(e)
      }
      className="grid gap-4"
      noValidate
    >
      <FormField label="Name" error={errors.name?.message}>
        <Input autoFocus {...form.register("name")} />
      </FormField>
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="Website" error={errors.website?.message}>
          <Input placeholder="acme.com" inputMode="url" {...form.register("website")} />
        </FormField>
        <FormField
          label="Domain"
          error={errors.domain?.message}
          hint={
            takenBy ? (
              <Link
                to="/companies/$companyId"
                params={{ companyId: takenBy }}
                className="font-medium text-primary underline"
              >
                Open the existing company
              </Link>
            ) : (
              "Filled from the website if empty. Used to detect duplicates."
            )
          }
        >
          <Input placeholder="acme.com" {...form.register("domain")} />
        </FormField>
        <FormField label="Industry" error={errors.industry?.message}>
          <Input {...form.register("industry")} />
        </FormField>
        <FormField label="Employees" error={errors.employee_count?.message}>
          <Input inputMode="numeric" {...form.register("employee_count")} />
        </FormField>
        <FormField label="Country" error={errors.country?.message}>
          <Input {...form.register("country")} />
        </FormField>
        <FormField label="City" error={errors.city?.message}>
          <Input {...form.register("city")} />
        </FormField>
      </div>
      <FormField label="Description" error={errors.description?.message}>
        <Textarea rows={3} {...form.register("description")} />
      </FormField>
      <div className="flex justify-end gap-2 pt-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? "Saving…" : company ? "Save changes" : "Create company"}
        </Button>
      </div>
    </form>
  );
}
