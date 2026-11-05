import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { api, errorMessage, unwrap } from "@/lib/api/client";

/** Fill an empty workspace with fictional sample companies, to explore the product. */
export function SampleDataButton() {
  const queryClient = useQueryClient();
  const load = useMutation({
    mutationFn: () => unwrap(api.POST("/sample-data")),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries();
      toast.success(
        `Loaded ${String(result.companies)} fictional companies` +
          (result.briefs ? ` with ${String(result.briefs)} AI-written briefs.` : "."),
      );
    },
    onError: (error) => {
      toast.error(errorMessage(error));
    },
  });
  return (
    <Button
      variant="outline"
      disabled={load.isPending}
      onClick={() => {
        load.mutate();
      }}
    >
      <Sparkles aria-hidden />
      {load.isPending ? "Loading…" : "Load sample data"}
    </Button>
  );
}
