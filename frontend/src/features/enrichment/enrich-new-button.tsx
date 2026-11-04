import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";

import { enrichmentKeys, enrichNotYetEnriched, usageQuery } from "./api";
import { enrichErrorMessage } from "./ai-profile-card";

/** Queue every company that has never been enriched (up to today's remaining quota). */
export function EnrichNewButton({ variant = "outline" }: { variant?: "outline" | "default" }) {
  const queryClient = useQueryClient();
  const usage = useQuery(usageQuery);

  const enrich = useMutation({
    mutationFn: enrichNotYetEnriched,
    onSuccess: async (runs) => {
      await queryClient.invalidateQueries({ queryKey: enrichmentKeys.all });
      toast.success(
        runs.length === 0
          ? "Every company with a website has already been enriched."
          : `Enriching ${runs.length} ${runs.length === 1 ? "company" : "companies"} in the background.`,
      );
    },
    onError: (error) => {
      toast.error(enrichErrorMessage(error));
    },
  });

  const remaining = usage.data?.remaining_today;
  const disabled = enrich.isPending || usage.data?.configured === false || remaining === 0;
  return (
    <Button
      variant={variant}
      disabled={disabled}
      title={
        usage.data
          ? `${usage.data.used_today} of ${usage.data.daily_limit} enrichments used today`
          : undefined
      }
      onClick={() => {
        enrich.mutate();
      }}
    >
      <Sparkles aria-hidden />
      Enrich new companies
    </Button>
  );
}
