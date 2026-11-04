import { cn } from "@/lib/utils";

import { TIER_DESCRIPTIONS, type Tier } from "./api";

const TIER_STYLES: Record<Tier, string> = {
  A: "bg-success/15 text-success ring-success/30",
  B: "bg-accent text-accent-foreground ring-primary/25",
  C: "bg-warning/20 text-foreground ring-warning/40",
  D: "bg-muted text-muted-foreground ring-border",
};

/** "A 86": the tier letter (colour-coded) and the score, with an accessible description. */
export function TierBadge({
  tier,
  score,
  className,
}: {
  tier: Tier;
  score?: number;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset tabular-nums",
        TIER_STYLES[tier],
        className,
      )}
      title={TIER_DESCRIPTIONS[tier]}
    >
      <span aria-label={`Tier ${tier}`}>{tier}</span>
      {score !== undefined && (
        <span className="font-normal" aria-label={`score ${String(score)} of 100`}>
          {score}
        </span>
      )}
    </span>
  );
}
