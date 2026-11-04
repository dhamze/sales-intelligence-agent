import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { ConfirmDialog, FormDialog } from "@/components/ui/overlays";
import { Input } from "@/components/ui/primitives";
import { hasRole, meQuery } from "@/features/auth/api";
import { ApiError, errorMessage } from "@/lib/api/client";
import { handleSubmitError } from "@/lib/forms";

import { contactKeys, createContact, deleteContact, updateContact, type Contact } from "./api";
import { CompanyPicker, type CompanyChoice } from "./company-picker";

const text = (max: number) => z.string().trim().max(max, `At most ${max} characters.`);

const formSchema = z
  .object({
    first_name: text(100),
    last_name: text(100),
    email: z.union([z.literal(""), z.email("Enter a valid email address.")]),
    title: text(200),
    phone: text(50).regex(/^[0-9+().\-\s/x]*$/, "Use digits and + ( ) - only."),
    linkedin_url: text(2048),
    company: z.object({ id: z.string(), name: z.string() }).nullable(),
  })
  .refine((v) => v.email || v.first_name || v.last_name, {
    message: "Enter a name or an email address.",
    path: ["first_name"],
  });
type FormValues = z.infer<typeof formSchema>;
const FIELDS = ["first_name", "last_name", "email", "title", "phone", "linkedin_url"];

function toBody(v: FormValues) {
  const orNull = (s: string) => (s === "" ? null : s);
  return {
    first_name: orNull(v.first_name),
    last_name: orNull(v.last_name),
    email: orNull(v.email),
    title: orNull(v.title),
    phone: orNull(v.phone),
    linkedin_url: orNull(v.linkedin_url),
    company_id: v.company?.id ?? null,
  };
}

/** Create (no `contact`) or edit a contact in a dialog. */
export function ContactFormDialog({
  open,
  onOpenChange,
  contact,
  defaultCompany = null,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  contact?: Contact;
  defaultCompany?: CompanyChoice | null;
}) {
  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={contact ? `Edit ${contact.full_name || contact.email || "contact"}` : "New contact"}
    >
      {open && (
        <ContactForm
          contact={contact}
          defaultCompany={defaultCompany}
          onDone={() => {
            onOpenChange(false);
          }}
        />
      )}
    </FormDialog>
  );
}

function ContactForm({
  contact,
  defaultCompany,
  onDone,
}: {
  contact: Contact | undefined;
  defaultCompany: CompanyChoice | null;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const { data: me } = useSuspenseQuery(meQuery);
  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      first_name: contact?.first_name ?? "",
      last_name: contact?.last_name ?? "",
      email: contact?.email ?? "",
      title: contact?.title ?? "",
      phone: contact?.phone ?? "",
      linkedin_url: contact?.linkedin_url ?? "",
      company:
        contact?.company_id && contact.company_name
          ? { id: contact.company_id, name: contact.company_name }
          : defaultCompany,
    },
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: contactKeys.all });

  const save = useMutation({
    mutationFn: (values: FormValues) =>
      contact ? updateContact(contact.id, toBody(values)) : createContact(toBody(values)),
    onSuccess: async () => {
      await refresh();
      toast.success(contact ? "Contact updated." : "Contact created.");
      onDone();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "contact_email_taken") {
        form.setError("email", { message: "Another contact already has this email." });
        return;
      }
      if (error instanceof ApiError && error.code === "company_not_found") {
        form.setError("company", { message: "That company no longer exists." });
        return;
      }
      handleSubmitError(error, form.setError, FIELDS);
    },
  });

  const remove = useMutation({
    mutationFn: () => deleteContact(contact?.id ?? ""),
    onSuccess: async () => {
      await refresh();
      toast.success("Contact deleted.");
      onDone();
    },
    onError: (error) => {
      toast.error(errorMessage(error));
    },
  });

  const { errors } = form.formState;
  return (
    <form
      onSubmit={(e) =>
        void form.handleSubmit((values) => {
          save.mutate(values);
        })(e)
      }
      className="grid gap-4"
      noValidate
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="First name" error={errors.first_name?.message}>
          <Input autoFocus {...form.register("first_name")} />
        </FormField>
        <FormField label="Last name" error={errors.last_name?.message}>
          <Input {...form.register("last_name")} />
        </FormField>
      </div>
      <FormField label="Email" error={errors.email?.message}>
        <Input type="email" {...form.register("email")} />
      </FormField>
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="Job title" error={errors.title?.message}>
          <Input {...form.register("title")} />
        </FormField>
        <FormField label="Phone" error={errors.phone?.message}>
          <Input type="tel" {...form.register("phone")} />
        </FormField>
      </div>
      <FormField label="LinkedIn URL" error={errors.linkedin_url?.message}>
        <Input inputMode="url" placeholder="linkedin.com/in/…" {...form.register("linkedin_url")} />
      </FormField>
      <FormField label="Company" error={errors.company?.message}>
        <Controller
          control={form.control}
          name="company"
          render={({ field }) => <CompanyPicker value={field.value} onChange={field.onChange} />}
        />
      </FormField>
      <div className="flex items-center justify-between gap-2 pt-2">
        <div>
          {contact && hasRole(me, "admin") && (
            <ConfirmDialog
              trigger={
                <Button type="button" variant="ghost" className="text-destructive">
                  Delete
                </Button>
              }
              title="Delete this contact?"
              description="The contact is removed permanently."
              confirmLabel="Delete contact"
              pending={remove.isPending}
              onConfirm={() => {
                remove.mutate();
              }}
            />
          )}
        </div>
        <div className="flex gap-2">
          <Button type="button" variant="outline" onClick={onDone}>
            Cancel
          </Button>
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? "Saving…" : contact ? "Save changes" : "Create contact"}
          </Button>
        </div>
      </div>
    </form>
  );
}
