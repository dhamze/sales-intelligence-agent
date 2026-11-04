import { createFileRoute } from "@tanstack/react-router";

import { PageHeader } from "@/components/ui/primitives";

export const Route = createFileRoute("/_app/imports/")({
  component: () => <PageHeader title="Imports" />,
});
