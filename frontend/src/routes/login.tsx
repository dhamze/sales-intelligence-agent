import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link, redirect, useNavigate } from "@tanstack/react-router";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Alert, Input } from "@/components/ui/primitives";
import { login, meQuery, resetSession } from "@/features/auth/api";
import { AuthLayout } from "@/features/auth/auth-layout";
import { safeRedirect } from "@/features/auth/safe-redirect";
import { ApiError, errorMessage } from "@/lib/api/client";

const searchSchema = z.object({
  redirect: z.string().optional(),
  expired: z.boolean().optional(),
});

export const Route = createFileRoute("/login")({
  validateSearch: searchSchema,
  beforeLoad: async ({ context, search }) => {
    if (await context.queryClient.query({ ...meQuery, staleTime: "static" })) {
      throw redirect({ to: safeRedirect(search.redirect) });
    }
  },
  component: LoginPage,
});

const formSchema = z.object({
  email: z.string().trim().min(1, "Enter your email address."),
  password: z.string().min(1, "Enter your password."),
});
type FormValues = z.infer<typeof formSchema>;

function LoginPage() {
  const search = Route.useSearch();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: { email: "", password: "" },
  });

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      resetSession(queryClient, await login(values));
      await navigate({ to: safeRedirect(search.redirect) });
    } catch (error) {
      form.setError("root", {
        message:
          error instanceof ApiError && error.code === "too_many_login_attempts"
            ? "Too many failed attempts. Please wait a few minutes and try again."
            : errorMessage(error),
      });
    }
  });

  const { errors, isSubmitting } = form.formState;
  return (
    <AuthLayout
      title="Log in"
      description="Welcome back. Log in to your workspace."
      footer={
        <>
          New here?{" "}
          <Link to="/signup" className="font-medium text-primary hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      <form onSubmit={(e) => void onSubmit(e)} className="grid gap-4" noValidate>
        {search.expired && !errors.root && (
          <Alert>Your session has ended. Please log in again.</Alert>
        )}
        {errors.root && <Alert tone="danger">{errors.root.message}</Alert>}
        <FormField label="Email" error={errors.email?.message}>
          <Input type="email" autoComplete="email" autoFocus {...form.register("email")} />
        </FormField>
        <FormField label="Password" error={errors.password?.message}>
          <Input type="password" autoComplete="current-password" {...form.register("password")} />
        </FormField>
        <Button type="submit" disabled={isSubmitting} className="mt-2">
          {isSubmitting ? "Logging in…" : "Log in"}
        </Button>
      </form>
    </AuthLayout>
  );
}
