import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { useEffect } from "react";
import { toast } from "sonner";

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
import { companyKeys } from "@/features/companies/api";
import { ApiError, errorMessage, type Schemas } from "@/lib/api/client";
import { formatDateTime } from "@/lib/utils";

import {
  companyEnrichmentQuery,
  enrichCompany,
  enrichmentKeys,
  FACT_LABELS,
  FAILURE_MESSAGES,
  isActive,
  usageQuery,
} from "./api";

interface Evidence {
  source_url: string;
  quote: string;
}
interface Fact {
  value: string | number;
  evidence: Evidence[];
}

function asFacts(raw: unknown): Fact[] {
  const list = Array.isArray(raw) ? raw : raw ? [raw] : [];
  return list.filter(
    (f): f is Fact =>
      typeof f === "object" && f !== null && "value" in f && Array.isArray((f as Fact).evidence),
  );
}

function shortUrl(url: string): string {
  try {
    const { hostname, pathname } = new URL(url);
    return hostname.replace(/^www\./, "") + (pathname === "/" ? "" : pathname);
  } catch {
    return url;
  }
}

export function enrichErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.code === "enrichment_daily_limit") {
    return "Today's enrichment limit has been reached. It resets at midnight (UTC).";
  }
  if (error instanceof ApiError && error.code === "enrichment_unavailable") {
    return "AI enrichment isn't configured on this server yet.";
  }
  return errorMessage(error);
}

/** The company's AI-extracted profile: every fact shown with the quote that supports it. */
export function AiProfileCard({ companyId }: { companyId: string }) {
  const queryClient = useQueryClient();
  const enrichment = useQuery(companyEnrichmentQuery(companyId));
  const usage = useQuery(usageQuery);

  const start = useMutation({
    mutationFn: () => enrichCompany(companyId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: enrichmentKeys.all });
    },
    onError: (error) => {
      toast.error(enrichErrorMessage(error));
    },
  });

  const data = enrichment.data;
  const run = data?.latest_run ?? null;
  const profile = data?.profile ?? null;
  const active = isActive(run);
  const configured = usage.data?.configured ?? true;

  // When a run finishes, the company record may have new (filled-in) values: refresh it once.
  const finishedRunId = run?.status === "succeeded" ? run.id : undefined;
  useEffect(() => {
    if (finishedRunId) {
      void queryClient.invalidateQueries({ queryKey: companyKeys.detail(companyId), exact: true });
      void queryClient.invalidateQueries({ queryKey: enrichmentKeys.usage });
    }
  }, [finishedRunId, companyId, queryClient]);

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="size-5 text-primary" aria-hidden />
            AI profile
          </CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">
            Read from the company's own website. Every fact shows the quote it came from.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={active || start.isPending || !configured}
          onClick={() => {
            start.mutate();
          }}
        >
          {active ? <Loader2 className="animate-spin" aria-hidden /> : <RefreshCw aria-hidden />}
          {profile ? "Re-enrich" : "Enrich"}
        </Button>
      </CardHeader>
      <CardContent>
        {enrichment.isPending ? (
          <Skeleton className="h-24" />
        ) : enrichment.isError ? (
          <Alert tone="danger">{errorMessage(enrichment.error)}</Alert>
        ) : (
          <div className="grid gap-4">
            {!configured && <Alert>AI enrichment isn't configured on this server yet.</Alert>}
            {active && (
              <Alert className="flex items-center gap-2">
                <Loader2 className="size-4 animate-spin" aria-hidden />
                Reading the website and extracting facts. This usually takes under a minute.
              </Alert>
            )}
            {run?.status === "failed" && (
              <Alert tone="danger">
                Last attempt failed:{" "}
                {FAILURE_MESSAGES[run.failure_reason ?? ""] ?? "Unknown error."}
              </Alert>
            )}
            {profile ? (
              <ProfileFacts profile={profile} />
            ) : (
              !active &&
              run?.status !== "failed" && (
                <p className="text-sm text-muted-foreground">
                  Not enriched yet. Enrich to read the company's website and build a profile.
                </p>
              )
            )}
            {usage.data && (
              <p className="text-xs text-muted-foreground">
                {usage.data.used_today} of {usage.data.daily_limit} enrichments used today.
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ProfileFacts({ profile }: { profile: Schemas["CompanyProfileOut"] }) {
  const entries = Object.keys(FACT_LABELS)
    .map((key) => [key, asFacts(profile.facts[key])] as const)
    .filter(([, facts]) => facts.length > 0);

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="primary">AI-extracted</Badge>
        <Badge tone="success">Quotes verified against the website</Badge>
      </div>
      {entries.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No facts could be verified from the website's text.
        </p>
      ) : (
        <dl className="grid gap-4">
          {entries.map(([key, facts]) => (
            <div key={key}>
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {FACT_LABELS[key]}
              </dt>
              {facts.map((fact, i) => (
                <dd key={i} className="mt-1">
                  <span className="text-sm">{String(fact.value)}</span>
                  {fact.evidence.slice(0, 1).map((e) => (
                    <blockquote
                      key={e.source_url + e.quote}
                      className="mt-1 border-l-2 border-primary/40 pl-3 text-xs text-muted-foreground"
                    >
                      &ldquo;{e.quote}&rdquo;{" "}
                      <a
                        href={e.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-0.5 text-primary hover:underline"
                      >
                        {shortUrl(e.source_url)}
                        <ExternalLink className="size-3" aria-hidden />
                      </a>
                    </blockquote>
                  ))}
                </dd>
              ))}
            </div>
          ))}
        </dl>
      )}
      <p className="border-t pt-3 text-xs text-muted-foreground">
        From {profile.sources.length} {profile.sources.length === 1 ? "page" : "pages"} ·{" "}
        {formatDateTime(profile.generated_at)} · {profile.model}
        {profile.facts_dropped > 0 &&
          ` · ${profile.facts_dropped} unverifiable ${profile.facts_dropped === 1 ? "fact" : "facts"} discarded`}
      </p>
    </div>
  );
}
