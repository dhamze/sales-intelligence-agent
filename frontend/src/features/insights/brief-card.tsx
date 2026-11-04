import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, ExternalLink, FileText, Loader2, RefreshCw } from "lucide-react";
import { useEffect } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/overlays";
import {
  Alert,
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Skeleton,
} from "@/components/ui/primitives";
import { isActive } from "@/features/enrichment/api";
import { ApiError, errorMessage } from "@/lib/api/client";
import { formatDateTime } from "@/lib/utils";

import {
  aiUsageQuery,
  BRIEF_FAILURES,
  briefQuery,
  insightKeys,
  requestBrief,
  type Brief,
  type BriefCitation,
  type BriefClaim,
  type BriefSource,
} from "./api";

const SOURCE_KINDS: Record<BriefSource["kind"], string> = {
  website: "Website",
  record: "Your data",
  score: "ICP fit",
  contacts: "Your contacts",
};

function requestErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.code === "brief_daily_limit") {
    return "Today's brief limit has been reached. It resets at midnight (UTC).";
  }
  if (error instanceof ApiError && error.code === "briefs_unavailable") {
    return "AI briefs aren't configured on this server yet.";
  }
  return errorMessage(error);
}

/** A short, cited account brief and a suggested outreach angle. */
export function BriefCard({ companyId }: { companyId: string }) {
  const queryClient = useQueryClient();
  const data = useQuery(briefQuery(companyId));
  const usage = useQuery(aiUsageQuery);

  const generate = useMutation({
    mutationFn: () => requestBrief(companyId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: insightKeys.brief(companyId) });
      await queryClient.invalidateQueries({ queryKey: insightKeys.usage });
    },
    onError: (error) => {
      toast.error(requestErrorMessage(error));
    },
  });

  const run = data.data?.latest_run ?? null;
  const brief = data.data?.brief ?? null;
  const active = isActive(run);
  const configured = usage.data?.configured ?? true;

  // A finished run has a cost: refresh the usage counters once.
  const finishedRunId = run && !active ? run.id : undefined;
  useEffect(() => {
    if (finishedRunId) void queryClient.invalidateQueries({ queryKey: insightKeys.usage });
  }, [finishedRunId, queryClient]);

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2">
            <FileText className="size-5 text-primary" aria-hidden />
            Account brief
          </CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">
            Written by AI only from the sources below. Every claim links to its quote.
          </p>
        </div>
        <Button
          variant={brief ? "outline" : "default"}
          size="sm"
          disabled={active || generate.isPending || !configured}
          onClick={() => {
            generate.mutate();
          }}
        >
          {active ? <Loader2 className="animate-spin" aria-hidden /> : <RefreshCw aria-hidden />}
          {brief ? "Regenerate" : "Generate brief"}
        </Button>
      </CardHeader>
      <CardContent>
        {data.isPending ? (
          <Skeleton className="h-32" />
        ) : data.isError ? (
          <Alert tone="danger">{errorMessage(data.error)}</Alert>
        ) : (
          <div className="grid gap-4">
            {!configured && <Alert>AI briefs aren&apos;t configured on this server yet.</Alert>}
            {active && (
              <Alert className="flex items-center gap-2">
                <Loader2 className="size-4 animate-spin" aria-hidden />
                Writing the brief and checking every citation. This usually takes under a minute.
              </Alert>
            )}
            {run?.status === "failed" && (
              <Alert tone="danger">
                Last attempt failed: {BRIEF_FAILURES[run.failure_reason ?? ""] ?? "Unknown error."}
              </Alert>
            )}
            {brief ? (
              <BriefBody brief={brief} />
            ) : (
              !active &&
              run?.status !== "failed" && (
                <p className="text-sm text-muted-foreground">
                  No brief yet. Generate one to get a summary, why this account fits, likely
                  priorities and a suggested way to open the conversation. Enrich the company first
                  for a richer brief.
                </p>
              )
            )}
            {usage.data && (
              <p className="text-xs text-muted-foreground">
                {usage.data.briefs_today} of {usage.data.brief_daily_limit} briefs used today.
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function BriefBody({ brief }: { brief: Brief }) {
  const sources = new Map(brief.sources.map((s) => [s.id, s]));
  return (
    <div className="grid gap-5">
      {brief.stale && (
        <Alert>
          This company&apos;s data changed after the brief was written. Regenerate to update it.
        </Alert>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="primary">AI-written</Badge>
        <Badge tone="success">Citations verified</Badge>
      </div>

      {brief.summary.length > 0 && (
        <p className="text-sm leading-relaxed">
          {brief.summary.map((claim, i) => (
            <span key={i}>
              {claim.text} <Citations claim={claim} sources={sources} />{" "}
            </span>
          ))}
        </p>
      )}
      <ClaimList title="Why they fit" claims={brief.fit} sources={sources} />
      <ClaimList title="Key facts" claims={brief.key_facts} sources={sources} />
      <ClaimList
        title="Likely priorities"
        note="AI inference, based on the cited facts"
        claims={brief.priorities}
        sources={sources}
      />
      {brief.outreach && <OutreachBox outreach={brief.outreach} sources={sources} />}
      {brief.gaps.length > 0 && (
        <section>
          <h4 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            What the sources don&apos;t say
          </h4>
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {brief.gaps.map((gap, i) => (
              <li key={i}>{gap}</li>
            ))}
          </ul>
        </section>
      )}

      <footer className="grid gap-2 border-t pt-3 text-xs text-muted-foreground">
        <ol className="flex flex-wrap gap-x-4 gap-y-1" aria-label="Sources">
          {brief.sources.map((s) => (
            <li key={s.id}>
              <span className="font-medium">{s.id}</span>{" "}
              {s.url ? (
                <a
                  href={s.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline"
                >
                  {s.title}
                </a>
              ) : (
                s.title
              )}
            </li>
          ))}
        </ol>
        <p>
          {formatDateTime(brief.generated_at)} · {brief.model}
          {brief.claims_dropped > 0 &&
            ` · ${String(brief.claims_dropped)} unverifiable ${brief.claims_dropped === 1 ? "claim" : "claims"} removed`}
        </p>
      </footer>
    </div>
  );
}

function ClaimList({
  title,
  note,
  claims,
  sources,
}: {
  title: string;
  note?: string;
  claims: BriefClaim[];
  sources: Map<string, BriefSource>;
}) {
  if (claims.length === 0) return null;
  return (
    <section>
      <h4 className="mb-1.5 flex flex-wrap items-baseline gap-x-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {title}
        {note && <span className="normal-case tracking-normal">({note})</span>}
      </h4>
      <ul className="list-disc space-y-1 pl-5 text-sm" aria-label={title}>
        {claims.map((claim, i) => (
          <li key={i}>
            {claim.text} <Citations claim={claim} sources={sources} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function Citations({
  claim,
  sources,
}: {
  claim: { citations: BriefCitation[] };
  sources: Map<string, BriefSource>;
}) {
  return (
    <span className="inline-flex flex-wrap gap-1 align-baseline">
      {claim.citations.map((c, i) => (
        <CitationChip key={i} citation={c} source={sources.get(c.source_id)} />
      ))}
    </span>
  );
}

function CitationChip({ citation, source }: { citation: BriefCitation; source?: BriefSource }) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="rounded bg-accent px-1 text-[0.7rem] font-medium leading-4 text-accent-foreground hover:bg-primary hover:text-primary-foreground"
          aria-label={`Source ${citation.source_id}: show quote`}
        >
          {citation.source_id}
        </button>
      </PopoverTrigger>
      <PopoverContent>
        <p className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
          <Badge>{source ? SOURCE_KINDS[source.kind] : "Source"}</Badge>
          <span className="truncate">{source?.title ?? citation.source_id}</span>
        </p>
        <blockquote className="border-l-2 border-primary/40 pl-3">
          &ldquo;{citation.quote}&rdquo;
        </blockquote>
        {source?.url && (
          <a
            href={source.url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2 inline-flex items-center gap-1 text-xs text-primary hover:underline"
          >
            Open page
            <ExternalLink className="size-3" aria-hidden />
          </a>
        )}
      </PopoverContent>
    </Popover>
  );
}

function OutreachBox({
  outreach,
  sources,
}: {
  outreach: NonNullable<Brief["outreach"]>;
  sources: Map<string, BriefSource>;
}) {
  const copy = async () => {
    const text = [
      outreach.opening_line,
      "",
      ...outreach.discovery_questions.map((q) => `- ${q}`),
    ].join("\n");
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Copied the opening line and questions.");
    } catch {
      toast.error("Couldn't copy. Select the text and copy it instead.");
    }
  };
  return (
    <section className="rounded-lg border bg-muted/30 p-4" aria-label="Outreach angle">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Outreach angle
        </h4>
        <Button variant="ghost" size="sm" onClick={() => void copy()}>
          <Copy aria-hidden />
          Copy
        </Button>
      </div>
      <p className="text-sm">
        {outreach.angle} <Citations claim={outreach} sources={sources} />
      </p>
      <blockquote className="mt-3 border-l-2 border-primary/40 pl-3 text-sm italic">
        {outreach.opening_line}
      </blockquote>
      {outreach.discovery_questions.length > 0 && (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm" aria-label="Discovery questions">
          {outreach.discovery_questions.map((q, i) => (
            <li key={i}>{q}</li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-muted-foreground">
        A suggestion to adapt, never sent automatically.
      </p>
    </section>
  );
}
