import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RefreshCw, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/overlays";
import {
  Alert,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  NativeSelect,
  Skeleton,
} from "@/components/ui/primitives";
import { companyKeys, facetsQuery } from "@/features/companies/api";
import { errorMessage } from "@/lib/api/client";
import { useDebouncedValue } from "@/lib/hooks";
import { cn, formatNumber } from "@/lib/utils";

import {
  AI_INDUSTRIES,
  BUSINESS_MODELS,
  CRITERION_LABELS,
  deleteIcp,
  icpQuery,
  IMPORTANCE_LABELS,
  isRescoring,
  previewQuery,
  rescoreAll,
  saveIcp,
  scoringKeys,
  TIER_DESCRIPTIONS,
  TIERS,
  type BusinessModel,
  type Criterion,
  type CriterionKind,
  type ICP,
  type ICPDefinition,
  type ICPPreview,
} from "./api";
import { TierBadge } from "./tier-badge";

// --- Draft state: what the form holds (strings for number inputs, every criterion present) ---

interface Common {
  enabled: boolean;
  importance: number;
  must_have: boolean;
}
interface Draft {
  industry: Common & { industries: string[] };
  size: Common & { min: string; max: string };
  country: Common & { countries: string[] };
  business_model: Common & { models: BusinessModel[] };
  keywords: Common & { keywords: string[] };
  has_contacts: Common & { min_contacts: string };
}

const KINDS: CriterionKind[] = [
  "industry",
  "size",
  "country",
  "business_model",
  "keywords",
  "has_contacts",
];

const HINTS: Record<CriterionKind, string> = {
  industry: "Industries you sell to. Matches your data or the AI profile.",
  size: "Number of employees. AI estimates (e.g. 51–200) that only overlap count half.",
  country: "Where the company is based. “DE”, “Germany” and “Deutschland” all match.",
  business_model: "From the AI profile (enrich companies to fill it in).",
  keywords: "Words to find in the description or the verified website facts.",
  has_contacts: "Companies where you already know someone.",
};

function emptyDraft(): Draft {
  const off = { enabled: false, importance: 3, must_have: false };
  return {
    industry: { ...off, industries: [] },
    size: { ...off, min: "", max: "" },
    country: { ...off, countries: [] },
    business_model: { ...off, models: [] },
    keywords: { ...off, keywords: [] },
    has_contacts: { ...off, min_contacts: "1" },
  };
}

function fromDefinition(definition: ICPDefinition | undefined): Draft {
  const draft = emptyDraft();
  for (const c of definition?.criteria ?? []) {
    const common = { enabled: true, importance: c.importance, must_have: c.must_have };
    switch (c.kind) {
      case "industry":
        draft.industry = { ...common, industries: c.industries };
        break;
      case "size":
        draft.size = {
          ...common,
          min: c.min_employees == null ? "" : String(c.min_employees),
          max: c.max_employees == null ? "" : String(c.max_employees),
        };
        break;
      case "country":
        draft.country = { ...common, countries: c.countries };
        break;
      case "business_model":
        draft.business_model = { ...common, models: c.models };
        break;
      case "keywords":
        draft.keywords = { ...common, keywords: c.keywords };
        break;
      case "has_contacts":
        draft.has_contacts = { ...common, min_contacts: String(c.min_contacts) };
        break;
    }
  }
  return draft;
}

function parseCount(text: string): number | null | "invalid" {
  if (!text.trim()) return null;
  return /^\d+$/.test(text.trim()) ? Number(text.trim()) : "invalid";
}

type Errors = Partial<Record<CriterionKind | "form", string>>;

/** The draft as an API definition, or the problems that prevent it. Mirrors server validation. */
export function toDefinition(draft: Draft): { definition?: ICPDefinition; errors: Errors } {
  const errors: Errors = {};
  const criteria: Criterion[] = [];
  for (const kind of KINDS) {
    const d = draft[kind];
    if (!d.enabled) continue;
    const common = { importance: d.importance, must_have: d.must_have };
    switch (kind) {
      case "industry":
        if (!draft.industry.industries.length) errors.industry = "Add at least one industry.";
        else criteria.push({ kind, ...common, industries: draft.industry.industries });
        break;
      case "size": {
        const min = parseCount(draft.size.min);
        const max = parseCount(draft.size.max);
        if (min === "invalid" || max === "invalid") errors.size = "Use whole numbers.";
        else if (min === null && max === null) errors.size = "Set a minimum or a maximum.";
        else if (min !== null && max !== null && min > max)
          errors.size = "The minimum is larger than the maximum.";
        else criteria.push({ kind, ...common, min_employees: min, max_employees: max });
        break;
      }
      case "country":
        if (!draft.country.countries.length) errors.country = "Add at least one country.";
        else criteria.push({ kind, ...common, countries: draft.country.countries });
        break;
      case "business_model":
        if (!draft.business_model.models.length)
          errors.business_model = "Pick at least one business model.";
        else criteria.push({ kind, ...common, models: draft.business_model.models });
        break;
      case "keywords":
        if (!draft.keywords.keywords.length) errors.keywords = "Add at least one keyword.";
        else criteria.push({ kind, ...common, keywords: draft.keywords.keywords });
        break;
      case "has_contacts": {
        const n = parseCount(draft.has_contacts.min_contacts);
        if (typeof n !== "number" || n < 1 || n > 1000)
          errors.has_contacts = "Enter a number from 1 to 1,000.";
        else criteria.push({ kind, ...common, min_contacts: n });
        break;
      }
    }
  }
  if (!KINDS.some((k) => draft[k].enabled)) errors.form = "Turn on at least one criterion.";
  return Object.keys(errors).length ? { errors } : { definition: { criteria }, errors };
}

// --- The builder ----------------------------------------------------------------------------

/** Settings card: define the ideal customer profile and preview its effect live. */
export function IcpBuilder({ canEdit }: { canEdit: boolean }) {
  const icp = useQuery(icpQuery);
  return (
    <Card id="icp" className="scroll-mt-6">
      <CardHeader>
        <CardTitle>Ideal customer profile</CardTitle>
        <CardDescription>
          Describe the companies you want to win. Every company gets a 0–100 fit score with the
          reasons, so your team knows who to work first.
          {!canEdit && " Only admins can change it."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {icp.isPending ? (
          <Skeleton className="h-64" />
        ) : icp.isError ? (
          <Alert tone="danger">{errorMessage(icp.error)}</Alert>
        ) : (
          <Editor key={icp.data?.version ?? 0} saved={icp.data} canEdit={canEdit} />
        )}
      </CardContent>
    </Card>
  );
}

function Editor({ saved, canEdit }: { saved: ICP | null; canEdit: boolean }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft>(() => fromDefinition(saved?.definition));
  const [showErrors, setShowErrors] = useState(false);
  const { definition, errors } = useMemo(() => toDefinition(draft), [draft]);
  // Compare in the form's own shape: the API may order fields differently.
  const savedNormalized = useMemo(
    () => (saved ? toDefinition(fromDefinition(saved.definition)).definition : undefined),
    [saved],
  );
  const dirty = JSON.stringify(definition ?? null) !== JSON.stringify(savedNormalized ?? null);

  const update = <K extends CriterionKind>(kind: K, patch: Partial<Draft[K]>) => {
    setDraft((d) => ({ ...d, [kind]: { ...d[kind], ...patch } }));
  };

  const refreshScores = async () => {
    await queryClient.invalidateQueries({ queryKey: scoringKeys.icp });
    await queryClient.invalidateQueries({ queryKey: companyKeys.all });
  };

  const save = useMutation({
    mutationFn: saveIcp,
    onSuccess: async (result) => {
      queryClient.setQueryData(scoringKeys.icp, result);
      await refreshScores();
      toast.success(
        result.status.total_companies
          ? `Saved. Rescoring ${formatNumber(result.status.total_companies)} companies in the background.`
          : "Saved. New companies will be scored as they're added.",
      );
    },
    onError: (error) => {
      toast.error(errorMessage(error));
    },
  });
  const remove = useMutation({
    mutationFn: deleteIcp,
    onSuccess: async () => {
      queryClient.setQueryData(scoringKeys.icp, null);
      await refreshScores();
      toast.success("ICP removed. Scores were cleared.");
    },
    onError: (error) => {
      toast.error(errorMessage(error));
    },
  });
  const rescore = useMutation({
    mutationFn: rescoreAll,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: scoringKeys.icp });
      toast.success("Recalculating every score in the background.");
    },
    onError: (error) => {
      toast.error(errorMessage(error));
    },
  });

  // When the background rescore finishes, lists and company pages show the new scores.
  const rescoring = isRescoring(saved);
  const wasRescoring = useRef(rescoring);
  useEffect(() => {
    if (wasRescoring.current && !rescoring)
      void queryClient.invalidateQueries({ queryKey: companyKeys.all });
    wasRescoring.current = rescoring;
  }, [rescoring, queryClient]);

  const visibleErrors = showErrors ? errors : {};

  return (
    <div className="grid gap-6 lg:grid-cols-5">
      <form
        className="grid gap-3 lg:col-span-3"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          setShowErrors(true);
          if (definition) save.mutate(definition);
        }}
      >
        <fieldset disabled={!canEdit} className="grid gap-3">
          <legend className="sr-only">Criteria</legend>
          {KINDS.map((kind) => (
            <CriterionSection
              key={kind}
              kind={kind}
              common={draft[kind]}
              error={visibleErrors[kind]}
              onCommon={(patch) => {
                update(kind, patch);
              }}
            >
              <CriterionInputs kind={kind} draft={draft} update={update} />
            </CriterionSection>
          ))}
        </fieldset>
        {visibleErrors.form && <Alert tone="danger">{visibleErrors.form}</Alert>}
        {canEdit && (
          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" disabled={save.isPending || (!dirty && !!saved)}>
              {save.isPending ? "Saving…" : saved ? "Save changes" : "Save ICP"}
            </Button>
            {dirty && saved && (
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setDraft(fromDefinition(saved.definition));
                  setShowErrors(false);
                }}
              >
                Discard changes
              </Button>
            )}
            {saved && (
              <>
                <Button
                  type="button"
                  variant="outline"
                  className="ml-auto"
                  disabled={rescore.isPending || rescoring}
                  onClick={() => {
                    rescore.mutate();
                  }}
                >
                  <RefreshCw aria-hidden />
                  Recalculate
                </Button>
                <ConfirmDialog
                  trigger={
                    <Button type="button" variant="outline" className="text-destructive">
                      Remove ICP
                    </Button>
                  }
                  title="Remove the ideal customer profile?"
                  description="Every company's score is cleared. You can define a new profile at any time."
                  confirmLabel="Remove"
                  pending={remove.isPending}
                  onConfirm={() => {
                    remove.mutate();
                  }}
                />
              </>
            )}
          </div>
        )}
        {saved && <ScoringStatusLine icp={saved} />}
      </form>

      <aside className="lg:col-span-2" aria-label="Preview">
        {canEdit ? (
          <PreviewPanel definition={definition} />
        ) : (
          <p className="text-sm text-muted-foreground">
            Sort and filter the company list by ICP fit to see who to work first.
          </p>
        )}
      </aside>
    </div>
  );
}

function ScoringStatusLine({ icp }: { icp: ICP }) {
  const { total_companies: total, scored_current: scored } = icp.status;
  if (scored < total) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
        <Loader2 className="size-4 animate-spin" aria-hidden />
        Recalculating scores… {formatNumber(scored)} of {formatNumber(total)} companies done.
      </p>
    );
  }
  return (
    <p className="text-sm text-muted-foreground" role="status">
      All {formatNumber(total)} {total === 1 ? "company is" : "companies are"} scored with the
      current profile.
    </p>
  );
}

// --- One criterion ----------------------------------------------------------------------------

function CriterionSection({
  kind,
  common,
  error,
  onCommon,
  children,
}: {
  kind: CriterionKind;
  common: Common;
  error?: string;
  onCommon: (patch: Partial<Common>) => void;
  children: ReactNode;
}) {
  const id = `icp-${kind}`;
  return (
    <section
      className={cn(
        "rounded-lg border p-4 transition-colors",
        common.enabled ? "bg-card" : "bg-muted/30",
        error && "border-destructive/50",
      )}
      aria-labelledby={`${id}-label`}
    >
      <label className="flex cursor-pointer items-start gap-3">
        <input
          type="checkbox"
          className="mt-0.5 size-4 accent-[var(--primary)]"
          checked={common.enabled}
          onChange={(e) => {
            onCommon({ enabled: e.target.checked });
          }}
        />
        <span>
          <span id={`${id}-label`} className="block text-sm font-medium">
            {CRITERION_LABELS[kind]}
          </span>
          <span className="block text-xs text-muted-foreground">{HINTS[kind]}</span>
        </span>
      </label>
      {common.enabled && (
        <div className="mt-3 grid gap-3 pl-7">
          {children}
          <div className="flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-2 text-sm">
              Importance
              <NativeSelect
                className="h-8 w-auto"
                value={common.importance}
                onChange={(e) => {
                  onCommon({ importance: Number(e.target.value) });
                }}
              >
                {[1, 2, 3, 4, 5].map((n) => (
                  <option key={n} value={n}>
                    {IMPORTANCE_LABELS[n]} ({n * 10} pts)
                  </option>
                ))}
              </NativeSelect>
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4 accent-[var(--primary)]"
                checked={common.must_have}
                onChange={(e) => {
                  onCommon({ must_have: e.target.checked });
                }}
              />
              Must-have
              <span className="text-xs text-muted-foreground">(failing it scores 0)</span>
            </label>
          </div>
          {error && (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function CriterionInputs({
  kind,
  draft,
  update,
}: {
  kind: CriterionKind;
  draft: Draft;
  update: <K extends CriterionKind>(kind: K, patch: Partial<Draft[K]>) => void;
}) {
  const facets = useQuery(facetsQuery);
  switch (kind) {
    case "industry":
      return (
        <TagInput
          label="Industries"
          values={draft.industry.industries}
          max={30}
          suggestions={unique([
            ...(facets.data?.industries.map((f) => f.value) ?? []),
            ...AI_INDUSTRIES,
          ])}
          onChange={(industries) => {
            update("industry", { industries });
          }}
        />
      );
    case "size":
      return (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <label className="flex items-center gap-2">
            From
            <Input
              className="h-8 w-28"
              inputMode="numeric"
              placeholder="any"
              aria-label="Minimum employees"
              value={draft.size.min}
              onChange={(e) => {
                update("size", { min: e.target.value });
              }}
            />
          </label>
          <label className="flex items-center gap-2">
            to
            <Input
              className="h-8 w-28"
              inputMode="numeric"
              placeholder="any"
              aria-label="Maximum employees"
              value={draft.size.max}
              onChange={(e) => {
                update("size", { max: e.target.value });
              }}
            />
          </label>
          employees
        </div>
      );
    case "country":
      return (
        <TagInput
          label="Countries"
          values={draft.country.countries}
          max={50}
          suggestions={facets.data?.countries.map((f) => f.value) ?? []}
          onChange={(countries) => {
            update("country", { countries });
          }}
        />
      );
    case "business_model":
      return (
        <div className="flex flex-wrap gap-4" role="group" aria-label="Business models">
          {BUSINESS_MODELS.map((model) => (
            <label key={model} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4 accent-[var(--primary)]"
                checked={draft.business_model.models.includes(model)}
                onChange={(e) => {
                  const models = draft.business_model.models;
                  update("business_model", {
                    models: e.target.checked
                      ? [...models, model]
                      : models.filter((m) => m !== model),
                  });
                }}
              />
              {model}
            </label>
          ))}
        </div>
      );
    case "keywords":
      return (
        <TagInput
          label="Keywords"
          values={draft.keywords.keywords}
          max={20}
          minLength={2}
          onChange={(keywords) => {
            update("keywords", { keywords });
          }}
        />
      );
    case "has_contacts":
      return (
        <label className="flex items-center gap-2 text-sm">
          At least
          <Input
            className="h-8 w-24"
            inputMode="numeric"
            aria-label="Minimum contacts"
            value={draft.has_contacts.min_contacts}
            onChange={(e) => {
              update("has_contacts", { min_contacts: e.target.value });
            }}
          />
          contacts
        </label>
      );
  }
}

function unique(values: string[]): string[] {
  const seen = new Set<string>();
  return values.filter((v) => {
    const key = v.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** Type a value and press Enter (or comma) to add it; suggestions come from a datalist. */
function TagInput({
  label,
  values,
  onChange,
  suggestions = [],
  max,
  minLength = 1,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  suggestions?: string[];
  max: number;
  minLength?: number;
}) {
  const [text, setText] = useState("");
  const listId = `${label.toLowerCase()}-suggestions`;

  const add = () => {
    const value = text.trim().replace(/,$/, "").trim();
    if (value.length < minLength || values.length >= max) return;
    if (!values.some((v) => v.toLowerCase() === value.toLowerCase())) {
      onChange([...values, value]);
    }
    setText("");
  };

  return (
    <div className="grid gap-2">
      {values.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label={label}>
          {values.map((value) => (
            <li
              key={value}
              className="inline-flex items-center gap-1 rounded-full bg-accent py-0.5 pl-2.5 pr-1 text-xs text-accent-foreground"
            >
              {value}
              <button
                type="button"
                className="rounded-full p-0.5 hover:bg-background/60"
                aria-label={`Remove ${value}`}
                onClick={() => {
                  onChange(values.filter((v) => v !== value));
                }}
              >
                <X className="size-3" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
      <Input
        className="h-8"
        aria-label={`Add ${label.toLowerCase()}`}
        placeholder={values.length >= max ? `Up to ${String(max)}` : "Type and press Enter"}
        list={suggestions.length ? listId : undefined}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            add();
          } else if (e.key === "Backspace" && !text && values.length) {
            onChange(values.slice(0, -1));
          }
        }}
        onBlur={add}
      />
      {suggestions.length > 0 && (
        <datalist id={listId}>
          {suggestions
            .filter((s) => !values.some((v) => v.toLowerCase() === s.toLowerCase()))
            .map((s) => (
              <option key={s} value={s} />
            ))}
        </datalist>
      )}
    </div>
  );
}

// --- Live preview ----------------------------------------------------------------------------

function PreviewPanel({ definition }: { definition?: ICPDefinition }) {
  // Wait until editing pauses, so one preview runs instead of one per keystroke.
  const debounced = useDebouncedValue(definition ? JSON.stringify(definition) : "", 500);
  const parsed = useMemo(
    () => (debounced ? (JSON.parse(debounced) as ICPDefinition) : undefined),
    [debounced],
  );
  const preview = useQuery({
    ...previewQuery(parsed ?? { criteria: [] }),
    enabled: !!parsed,
    placeholderData: (previous) => previous,
  });

  return (
    <div className="grid gap-4 rounded-lg border bg-muted/20 p-4">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold">Preview</h4>
        {preview.isFetching && (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" aria-hidden />
            Calculating…
          </span>
        )}
      </div>
      {!parsed ? (
        <p className="text-sm text-muted-foreground">
          Turn on a criterion and fill it in to see how your companies would score.
        </p>
      ) : preview.isError ? (
        <Alert tone="danger">{errorMessage(preview.error)}</Alert>
      ) : !preview.data ? (
        <Skeleton className="h-48" />
      ) : (
        <PreviewResult preview={preview.data} />
      )}
    </div>
  );
}

function PreviewResult({ preview }: { preview: ICPPreview }) {
  const total = preview.total_companies;
  if (total === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No companies yet. Import some to see how they would score.
      </p>
    );
  }
  return (
    <>
      <div>
        <div className="flex h-3 overflow-hidden rounded-full bg-muted" aria-hidden>
          {TIERS.map((tier) => (
            <div
              key={tier}
              className={cn(
                tier === "A" && "bg-success",
                tier === "B" && "bg-primary",
                tier === "C" && "bg-warning",
                tier === "D" && "bg-muted-foreground/40",
              )}
              style={{ width: `${String((preview.tiers[tier] / total) * 100)}%` }}
            />
          ))}
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
          {TIERS.map((tier) => (
            <div key={tier} className="flex items-center gap-2">
              <dt>
                <TierBadge tier={tier} />
                <span className="sr-only"> {TIER_DESCRIPTIONS[tier]}</span>
              </dt>
              <dd className="tabular-nums">
                {formatNumber(preview.tiers[tier])}{" "}
                <span className="text-xs text-muted-foreground">
                  ({Math.round((preview.tiers[tier] / total) * 100)}%)
                </span>
              </dd>
            </div>
          ))}
        </dl>
        <p className="mt-2 text-xs text-muted-foreground">
          {formatNumber(total)} companies · average data completeness{" "}
          {Math.round(preview.average_completeness * 100)}%
        </p>
      </div>
      <div>
        <h5 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Best fits
        </h5>
        <ol className="grid gap-1.5" aria-label="Best fits">
          {preview.top.map((company) => (
            <li key={company.company_id} className="flex items-center justify-between gap-2">
              <span className="truncate text-sm">{company.name}</span>
              <TierBadge tier={company.tier} score={company.score} />
            </li>
          ))}
        </ol>
      </div>
    </>
  );
}
