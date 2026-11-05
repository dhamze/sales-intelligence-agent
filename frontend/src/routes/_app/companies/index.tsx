import { useInfiniteQuery, useQuery, useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { ArrowDown, ArrowUp, Building2, FileUp, Plus, Search, Target, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { FormDialog } from "@/components/ui/overlays";
import {
  Alert,
  EmptyState,
  Input,
  NativeSelect,
  PageHeader,
  Skeleton,
} from "@/components/ui/primitives";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  companiesQuery,
  companySearchSchema,
  facetsQuery,
  hasFilters,
  SIZE_BUCKETS,
  type CompanySearch,
  type CompanySort,
} from "@/features/companies/api";
import { hasRole, meQuery } from "@/features/auth/api";
import { CompanyForm } from "@/features/companies/company-form";
import { SampleDataButton } from "@/features/companies/sample-data-button";
import { FilterMenu } from "@/features/companies/filter-menu";
import { EnrichNewButton } from "@/features/enrichment/enrich-new-button";
import { icpQuery, TIER_DESCRIPTIONS, TIERS } from "@/features/scoring/api";
import { TierBadge } from "@/features/scoring/tier-badge";
import { errorMessage } from "@/lib/api/client";
import { useDebouncedValue } from "@/lib/hooks";
import { formatDate, formatNumber } from "@/lib/utils";

export const Route = createFileRoute("/_app/companies/")({
  validateSearch: companySearchSchema,
  component: CompaniesPage,
});

function CompaniesPage() {
  const search = Route.useSearch();
  const navigate = useNavigate({ from: Route.fullPath });
  const [creating, setCreating] = useState(false);

  const setSearch = (patch: Partial<CompanySearch>) =>
    void navigate({ search: (prev) => ({ ...prev, ...patch }), replace: true });

  const companies = useInfiniteQuery(companiesQuery(search));
  const facets = useQuery(facetsQuery);
  const icp = useQuery(icpQuery);
  const scoring = !!icp.data;
  const { data: me } = useSuspenseQuery(meQuery);
  const isAdmin = hasRole(me, "admin");
  const rows = companies.data?.pages.flatMap((page) => page.items) ?? [];
  const filtered = hasFilters(search);

  return (
    <>
      <PageHeader
        title="Companies"
        description="Your accounts. Search, filter and open a company to see its contacts."
        actions={
          <>
            <EnrichNewButton />
            <Button asChild variant="outline">
              <Link to="/imports">
                <FileUp aria-hidden />
                Import CSV
              </Link>
            </Button>
            <Button
              onClick={() => {
                setCreating(true);
              }}
            >
              <Plus aria-hidden />
              New company
            </Button>
          </>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <SearchBox
          value={search.q ?? ""}
          onChange={(q) => {
            setSearch({ q: q || undefined });
          }}
        />
        <FilterMenu
          label="Industry"
          options={facets.data?.industries ?? []}
          selected={search.industry ?? []}
          onChange={(industry) => {
            setSearch({ industry: industry.length ? industry : undefined });
          }}
        />
        <FilterMenu
          label="Country"
          options={facets.data?.countries ?? []}
          selected={search.country ?? []}
          onChange={(country) => {
            setSearch({ country: country.length ? country : undefined });
          }}
        />
        {scoring && (
          <FilterMenu
            label="ICP tier"
            options={TIERS.map((tier) => ({
              value: tier,
              label: (
                <span className="flex items-center gap-2">
                  <TierBadge tier={tier} />
                  {TIER_DESCRIPTIONS[tier]}
                </span>
              ),
            }))}
            selected={search.tier ?? []}
            onChange={(tier) => {
              setSearch({ tier: tier.length ? (tier as CompanySearch["tier"]) : undefined });
            }}
          />
        )}
        <NativeSelect
          aria-label="Company size"
          className="w-auto"
          value={search.size ?? ""}
          onChange={(e) => {
            setSearch({ size: (e.target.value || undefined) as CompanySearch["size"] });
          }}
        >
          <option value="">Any size</option>
          {Object.entries(SIZE_BUCKETS).map(([value, { label }]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </NativeSelect>
        {filtered && (
          <Button
            variant="ghost"
            onClick={() => void navigate({ search: { sort: search.sort }, replace: true })}
          >
            <X aria-hidden />
            Clear filters
          </Button>
        )}
      </div>

      {icp.isSuccess && !scoring && rows.length > 0 && (
        <Alert className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <span className="flex items-center gap-2">
            <Target className="size-4 text-primary" aria-hidden />
            Rank these companies by fit: describe your ideal customer once, and every company gets a
            score with the reasons.
          </span>
          <Link to="/settings" hash="icp" className="font-medium text-primary hover:underline">
            Set up ICP scoring
          </Link>
        </Alert>
      )}

      {companies.isError ? (
        <Alert tone="danger">{errorMessage(companies.error)}</Alert>
      ) : companies.isPending ? (
        <LoadingTable />
      ) : rows.length === 0 ? (
        filtered ? (
          <EmptyState
            icon={<Search />}
            title="No companies match your filters"
            description="Try a different search, or clear the filters."
          />
        ) : (
          <EmptyState
            icon={<Building2 />}
            title="No companies yet"
            description={
              isAdmin
                ? "Import your account list from a CSV file, add a company by hand, or explore with fictional sample data."
                : "Import your account list from a CSV file, or add a company by hand."
            }
            action={
              <div className="flex flex-wrap justify-center gap-2">
                <Button asChild>
                  <Link to="/imports">
                    <FileUp aria-hidden />
                    Import CSV
                  </Link>
                </Button>
                {isAdmin && <SampleDataButton />}
              </div>
            }
          />
        )
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <SortableHead label="Name" field="name" search={search} onSort={setSearch} />
                {scoring && (
                  <SortableHead
                    label="ICP fit"
                    field="icp_score"
                    descendingFirst
                    search={search}
                    onSort={setSearch}
                  />
                )}
                <TableHead>Industry</TableHead>
                <TableHead className="text-right">Employees</TableHead>
                <TableHead>Country</TableHead>
                <SortableHead label="Added" field="created_at" search={search} onSort={setSearch} />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((company) => (
                <TableRow key={company.id}>
                  <TableCell>
                    <Link
                      to="/companies/$companyId"
                      params={{ companyId: company.id }}
                      className="font-medium hover:text-primary hover:underline"
                    >
                      {company.name}
                    </Link>
                    {company.domain && (
                      <div className="text-xs text-muted-foreground">{company.domain}</div>
                    )}
                  </TableCell>
                  {scoring && (
                    <TableCell>
                      {company.icp_tier && company.icp_score !== null ? (
                        <TierBadge tier={company.icp_tier} score={company.icp_score} />
                      ) : (
                        <span className="text-xs text-muted-foreground">Not scored</span>
                      )}
                    </TableCell>
                  )}
                  <TableCell>{company.industry ?? "—"}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatNumber(company.employee_count)}
                  </TableCell>
                  <TableCell>{company.country ?? "—"}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDate(company.created_at)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
            <span>
              Showing {formatNumber(rows.length)} {rows.length === 1 ? "company" : "companies"}
              {search.q && !search.sort ? " · sorted by relevance" : ""}
            </span>
            {companies.hasNextPage && (
              <Button
                variant="outline"
                onClick={() => void companies.fetchNextPage()}
                disabled={companies.isFetchingNextPage}
              >
                {companies.isFetchingNextPage ? "Loading…" : "Load more"}
              </Button>
            )}
          </div>
        </>
      )}

      <FormDialog open={creating} onOpenChange={setCreating} title="New company">
        <CompanyForm
          onSaved={(company) => {
            setCreating(false);
            void navigate({ to: "/companies/$companyId", params: { companyId: company.id } });
          }}
          onCancel={() => {
            setCreating(false);
          }}
        />
      </FormDialog>
    </>
  );
}

/** Search input that updates the URL only after typing pauses (one request, not one per key). */
function SearchBox({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const [text, setText] = useState(value);
  const debounced = useDebouncedValue(text.trim(), 300);

  useEffect(() => {
    if (debounced !== value) onChange(debounced);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- react only to new debounced text
  }, [debounced]);

  return (
    <div className="relative min-w-60 flex-1">
      <Search
        className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
        aria-hidden
      />
      <Input
        type="search"
        aria-label="Search companies"
        placeholder="Search by name or domain…"
        className="pl-9"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
        }}
      />
    </div>
  );
}

function SortableHead({
  label,
  field,
  descendingFirst = false,
  search,
  onSort,
}: {
  label: string;
  field: "name" | "created_at" | "icp_score";
  /** First click sorts high-to-low (e.g. best fit first). */
  descendingFirst?: boolean;
  search: CompanySearch;
  onSort: (patch: Partial<CompanySearch>) => void;
}) {
  const current = search.sort ?? (search.q ? "relevance" : "-created_at");
  const direction = current === field ? "asc" : current === `-${field}` ? "desc" : undefined;
  const next: CompanySort = descendingFirst
    ? direction === "desc"
      ? field
      : `-${field}`
    : direction === "asc"
      ? `-${field}`
      : field;
  return (
    <TableHead
      aria-sort={direction === "asc" ? "ascending" : direction === "desc" ? "descending" : "none"}
    >
      <button
        type="button"
        className="inline-flex items-center gap-1 uppercase hover:text-foreground"
        onClick={() => {
          onSort({ sort: next });
        }}
      >
        {label}
        {direction === "asc" && <ArrowUp className="size-3" aria-hidden />}
        {direction === "desc" && <ArrowDown className="size-3" aria-hidden />}
      </button>
    </TableHead>
  );
}

function LoadingTable() {
  return (
    <div className="grid gap-2 rounded-xl border bg-card p-4" aria-busy="true" aria-label="Loading">
      {Array.from({ length: 8 }, (_, i) => (
        <Skeleton key={i} className="h-10" />
      ))}
    </div>
  );
}
