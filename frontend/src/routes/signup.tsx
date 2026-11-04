import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link, redirect, useNavigate } from "@tanstack/react-router";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Alert, Input } from "@/components/ui/primitives";
import { meQuery, resetSession, signup } from "@/features/auth/api";
import { AuthLayout } from "@/features/auth/auth-layout";
import { ApiError } from "@/lib/api/client";
import { handleSubmitError } from "@/lib/forms";

export const Route = createFileRoute("/signup")({
  beforeLoad: async ({ context }) => {
    if (await context.queryClient.query({ ...meQuery, staleTime: "static" }))
      throw redirect({ to: "/companies" });
  },
  component: SignupPage,
});

// Mirrors the backend rules for instant feedback; the server remains the authority.
const formSchema = z.object({
  name: z.string().trim().min(1, "Enter your name.").max(100),
  organization_name: z.string().trim().min(1, "Enter your company or team name.").max(100),
  email: z.email("Enter a valid email address.").max(320),
  password: z
    .string()
    .min(12, "Use at least 12 characters.")
    .max(128, "Use at most 128 characters."),
});
type FormValues = z.infer<typeof formSchema>;
const FIELDS = ["name", "organization_name", "email", "password"] as const;

function SignupPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: { name: "", organization_name: "", email: "", password: "" },
  });

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      resetSession(queryClient, await signup(values));
      await navigate({ to: "/companies" });
    } catch (error) {
      if (error instanceof ApiError && error.code === "email_taken") {
        form.setError("email", { message: "An account with this email already exists." });
        return;
      }
      handleSubmitError(error, form.setError, FIELDS);
    }
  });

  const { errors, isSubmitting } = form.formState;
  return (
    <AuthLayout
      title="Create your workspace"
      description="Import your accounts and find who to prioritise."
      footer={
        <>
          Already have an account?{" "}
          <Link to="/login" search={{}} className="font-medium text-primary hover:underline">
            Log in
          </Link>
        </>
      }
    >
      <form onSubmit={(e) => void onSubmit(e)} className="grid gap-4" noValidate>
        {errors.root && <Alert tone="danger">{errors.root.message}</Alert>}
        <FormField label="Your name" error={errors.name?.message}>
          <Input autoComplete="name" autoFocus {...form.register("name")} />
        </FormField>
        <FormField label="Company or team" error={errors.organization_name?.message}>
          <Input autoComplete="organization" {...form.register("organization_name")} />
        </FormField>
        <FormField label="Work email" error={errors.email?.message}>
          <Input type="email" autoComplete="email" {...form.register("email")} />
        </FormField>
        <FormField
          label="Password"
          error={errors.password?.message}
          hint="At least 12 characters. A short phrase is easy to remember and hard to guess."
        >
          <Input type="password" autoComplete="new-password" {...form.register("password")} />
        </FormField>
        <Button type="submit" disabled={isSubmitting} className="mt-2">
          {isSubmitting ? "Creating workspace…" : "Create workspace"}
        </Button>
      </form>
    </AuthLayout>
  );
}
