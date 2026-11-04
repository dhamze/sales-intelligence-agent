import { useQuery, useSuspenseQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Check, CircleHelp, Loader2, Minus, Target, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Alert,
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Skeleton,
} from "@/components/ui/primitives";
import { hasRole, meQuery } from "@/features/auth/api";
import { errorMessage, type Schemas } from "@/lib/api/client";
import { cn } from "@/lib/utils";

import { companyScoreQuery, CRITERION_LABELS, icpQuery, TIER_DESCRIPTIONS } from "./api";
import { TierBadge } from "./tier-badge";

type CriterionResult = Schemas["CriterionOut"];

const STATUS: Record<
  CriterionResult["status"],
  { icon: typeof Check; label: string; className: string }
> = {
  match: { icon: Check, label: "Match", className: "text-success" },
  partial: { icon: Minus, label: "Partial match", className: "text-warning" },
  miss: { icon: X, label: "No match", className: "text-destructive" },
  unknown: { icon: CircleHelp, label: "Unknown", className: "text-muted-foreground" },
};

/** How well the company fits the ideal customer profile, and exactly why. */
export function IcpFitCard({ companyId }: { companyId: string }) {
  const icp = useQuery(icpQuery);
  const score = useQuery({ ...companyScoreQuery(companyId), enabled: !!icp.data });
  const { data: me } = useSuspenseQuery(meQuery);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Target className="size-5 text-primary" aria-hidden />
          ICP fit
        </CardTitle>
      </CardHeader>
      <CardContent>
        {icp.isPending || (icp.data && score.isPending) ? (
          <Skeleton className="h-24" />
        ) : icp.isError || score.isError ? (
          <Alert tone="danger">{errorMessage(icp.error ?? score.error)}</Alert>
        ) : !icp.data ? (
          <div className="grid gap-3 text-sm text-muted-foreground">
            <p>
              Define your ideal customer profile to see how well each company fits, with the
              reasons.
            </p>
            {hasRole(me, "admin") ? (
              <Button asChild variant="outline" size="sm" className="justify-self-start">
                <Link to="/settings" hash="icp">
                  Set up ICP scoring
                </Link>
              </Button>
            ) : (
              <p>Ask an admin to set it up in Settings.</p>
            )}
          </div>
        ) : !score.data ? (
          <p className="text-sm text-muted-foreground">Not scored yet. This takes a moment.</p>
        ) : (
          <ScoreDetails score={score.data} />
        )}
      </CardContent>
    </Card>
  );
}

function ScoreDetails({ score }: { score: Schemas["CompanyScoreOut"] }) {
  const unknown = score.breakdown.filter((c) => c.status === "unknown").length;
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <TierBadge tier={score.tier} className="px-3 py-1 text-base" />
        <div>
          <p className="text-2xl font-semibold tabular-nums leading-none">
            {score.score}
            <span className="text-sm font-normal text-muted-foreground"> / 100</span>
          </p>
          <p className="mt-1 text-xs text-muted-foreground">{TIER_DESCRIPTIONS[score.tier]}</p>
        </div>
        {score.disqualified && <Badge tone="danger">Fails a must-have</Badge>}
      </div>

      {!score.current && (
        <Alert className="flex items-center gap-2">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          The ICP changed. This score is being recalculated.
        </Alert>
      )}

      <ul className="grid gap-3" aria-label="Score breakdown">
        {score.breakdown.map((c) => {
          const status = STATUS[c.status];
          const Icon = status.icon;
          return (
            <li key={c.kind} className="flex gap-3">
              <Icon
                className={cn("mt-0.5 size-4 shrink-0", status.className)}
                aria-label={status.label}
              />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="text-sm font-medium">
                    {(CRITERION_LABELS as Partial<Record<string, string>>)[c.kind] ?? c.kind}
                    {c.must_have && (
                      <Badge tone="neutral" className="ml-2">
                        Must-have
                      </Badge>
                    )}
                  </span>
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {formatPoints(c.points)} / {c.max_points} pts
                  </span>
                </div>
                <p className="break-words text-xs text-muted-foreground">{c.detail}</p>
              </div>
            </li>
          );
        })}
      </ul>

      <p className="border-t pt-3 text-xs text-muted-foreground">
        Data completeness {Math.round(score.completeness * 100)}%
        {unknown > 0 &&
          ` · ${String(unknown)} ${unknown === 1 ? "criterion" : "criteria"} unknown, counted as no match`}
      </p>
    </div>
  );
}

function formatPoints(points: number): string {
  return Number.isInteger(points) ? String(points) : points.toFixed(1);
}
