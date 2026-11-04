import { useQuery } from "@tanstack/react-query";

import {
  Alert,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Skeleton,
} from "@/components/ui/primitives";
import { errorMessage } from "@/lib/api/client";
import { formatNumber } from "@/lib/utils";

import { aiUsageQuery, PURPOSE_LABELS } from "./api";

function usd(value: string): string {
  return `$${Number(value).toFixed(2)}`;
}

/** Estimated AI spend of the organization, so cost is never a surprise. */
export function AiUsageCard() {
  const usage = useQuery(aiUsageQuery);
  return (
    <Card>
      <CardHeader>
        <CardTitle>AI usage</CardTitle>
        <CardDescription>
          Estimated cost of AI features (enrichment and briefs). Your Anthropic invoice is the final
          word.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {usage.isPending ? (
          <Skeleton className="h-24" />
        ) : usage.isError ? (
          <Alert tone="danger">{errorMessage(usage.error)}</Alert>
        ) : (
          <div className="grid gap-4">
            {!usage.data.configured && <Alert>AI isn&apos;t configured on this server yet.</Alert>}
            <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <Stat label="Today" value={usd(usage.data.cost_today_usd)} />
              <Stat label="This month" value={usd(usage.data.cost_month_usd)} />
              <Stat
                label="Briefs today"
                value={`${String(usage.data.briefs_today)} / ${String(usage.data.brief_daily_limit)}`}
              />
            </dl>
            {usage.data.month_by_purpose.length > 0 ? (
              <table className="w-full text-sm" aria-label="This month by feature">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="pb-1 font-medium">Feature</th>
                    <th className="pb-1 text-right font-medium">AI calls</th>
                    <th className="pb-1 text-right font-medium">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {usage.data.month_by_purpose.map((p) => (
                    <tr key={p.purpose} className="border-t">
                      <td className="py-1.5">{PURPOSE_LABELS[p.purpose] ?? p.purpose}</td>
                      <td className="py-1.5 text-right tabular-nums">{formatNumber(p.calls)}</td>
                      <td className="py-1.5 text-right tabular-nums">{usd(p.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="text-sm text-muted-foreground">No AI usage this month yet.</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-xl font-semibold tabular-nums">{value}</dd>
    </div>
  );
}
