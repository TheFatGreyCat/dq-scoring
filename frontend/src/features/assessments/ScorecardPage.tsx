import { useQuery } from "@tanstack/react-query";
import { ExternalLink, RotateCcw } from "lucide-react";
import { useEffect } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { getAssessment, listAssessments } from "../../api/endpoints";
import type { QualityGate, PublicationStatus } from "../../api/types";
import { CopyId } from "../../components/CopyId";
import { PageHeader } from "../../components/Field";
import { IdLookup } from "../../components/IdLookup";
import { ProblemAlert } from "../../components/ProblemAlert";
import { GateBadge, PublicationBadge } from "../../components/StatusBadge";
import { formatRatio, formatScore, formatTimestamp } from "../../lib/format";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { recent } from "../../lib/recent";
import type { SurfaceTranslationKey } from "../../lib/surfaceTranslations";
import { useSession } from "../auth/useSession";
import { RuleTable } from "./RuleTable";
import { DimensionTiles, ScoreHeader } from "./ScoreSummary";

type PageKey = TranslationKey | SurfaceTranslationKey;

const QUALITY_GATES: QualityGate[] = ["PASS", "WARN", "FAIL", "ERROR", "INSUFFICIENT_EVIDENCE"];
const PUBLICATION_STATUSES: PublicationStatus[] = ["PUBLISHED", "WITHHELD"];

export function AssessmentsPage() {
  const { email } = useSession();
  const { lang, t: rawT } = useI18n();
  const t = rawT as (key: PageKey, params?: Record<string, string | number>) => string;
  const [searchParams, setSearchParams] = useSearchParams();

  const page = parseInt(searchParams.get("page") || "1", 10) || 1;
  const assetId = searchParams.get("asset_id") || "";
  const qualityGate = searchParams.get("quality_gate") || "";
  const publicationStatus = searchParams.get("publication_status") || "";
  const createdFrom = searchParams.get("created_from") || "";
  const createdTo = searchParams.get("created_to") || "";

  const query = useQuery({
    queryKey: [
      "assessments",
      email,
      { page, assetId, qualityGate, publicationStatus, createdFrom, createdTo },
    ],
    queryFn: ({ signal }) =>
      listAssessments(
        {
          page,
          page_size: 25,
          asset_id: assetId || undefined,
          quality_gate: qualityGate && qualityGate !== "ALL" ? qualityGate : undefined,
          publication_status: publicationStatus && publicationStatus !== "ALL" ? publicationStatus : undefined,
          created_from: createdFrom ? new Date(createdFrom).toISOString() : undefined,
          created_to: createdTo ? new Date(createdTo).toISOString() : undefined,
        },
        signal,
      ),
  });

  const updateParam = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value && value !== "ALL") {
      next.set(key, value);
    } else {
      next.delete(key);
    }
    next.set("page", "1");
    setSearchParams(next);
  };

  const setPage = (nextPage: number) => {
    const next = new URLSearchParams(searchParams);
    next.set("page", String(nextPage));
    setSearchParams(next);
  };

  const resetFilters = () => {
    setSearchParams(new URLSearchParams());
  };

  const total = query.data?.total ?? 0;
  const items = query.data?.items ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("assessments.title")}
        description={t("assessments.subtitle")}
      />

      {/* Filter toolbar */}
      <section className="card space-y-4" aria-label={t("assessments.reset_filters")}>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
          <p className="text-xs font-semibold uppercase text-fg-muted">
            {t("assessments.reset_filters")}
          </p>
          <button
            type="button"
            onClick={resetFilters}
            className="btn-secondary text-xs flex items-center gap-1.5 px-2.5 py-1"
          >
            <RotateCcw className="size-3.5" />
            {t("assessments.reset_filters")}
          </button>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5 text-sm">
          <div>
            <label className="block text-xs text-fg-muted mb-1">{t("assessments.filter_asset")}</label>
            <input
              type="search"
              className="input text-xs mono"
              placeholder="Asset UUID…"
              value={assetId}
              onChange={(e) => updateParam("asset_id", e.target.value)}
            />
          </div>

          <div>
            <label className="block text-xs text-fg-muted mb-1">{t("assessments.filter_gate")}</label>
            <select
              className="input text-xs"
              value={qualityGate || "ALL"}
              onChange={(e) => updateParam("quality_gate", e.target.value)}
            >
              <option value="ALL">{t("common.all")}</option>
              {QUALITY_GATES.map((g) => (
                <option key={g} value={g}>{g}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs text-fg-muted mb-1">{t("assessments.filter_publication")}</label>
            <select
              className="input text-xs"
              value={publicationStatus || "ALL"}
              onChange={(e) => updateParam("publication_status", e.target.value)}
            >
              <option value="ALL">{t("common.all")}</option>
              {PUBLICATION_STATUSES.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs text-fg-muted mb-1">{t("assessments.filter_date_from")}</label>
            <input
              type="date"
              className="input text-xs"
              value={createdFrom}
              onChange={(e) => updateParam("created_from", e.target.value)}
            />
          </div>

          <div>
            <label className="block text-xs text-fg-muted mb-1">{t("assessments.filter_date_to")}</label>
            <input
              type="date"
              className="input text-xs"
              value={createdTo}
              onChange={(e) => updateParam("created_to", e.target.value)}
            />
          </div>
        </div>
      </section>

      {query.isError && <ProblemAlert error={query.error} onRetry={() => query.refetch()} />}
      {query.isPending && <p aria-busy>{t("common.loading")}</p>}

      {/* Assessment Table */}
      {query.isSuccess && (
        <section className="card space-y-4">
          {items.length === 0 ? (
            <p className="text-sm text-fg-muted py-4">{t("common.empty")}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-fg-muted border-b border-border">
                    <th scope="col" className="py-2.5 font-medium">{t("assessments.col_id")}</th>
                    <th scope="col" className="py-2.5 font-medium">{t("assessments.col_gate")}</th>
                    <th scope="col" className="py-2.5 font-medium text-right">{t("assessments.col_score")}</th>
                    <th scope="col" className="py-2.5 font-medium text-right">{t("assessments.col_coverage")}</th>
                    <th scope="col" className="py-2.5 font-medium">{t("assessments.col_publication")}</th>
                    <th scope="col" className="py-2.5 font-medium">{t("assessments.col_created")}</th>
                    <th scope="col" className="py-2.5 font-medium text-right">{t("assessments.col_actions")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {items.map((item) => (
                    <tr key={item.assessment_id} className="align-middle">
                      <td className="py-2.5 mono text-xs">
                        <Link
                          to={`/assessments/${item.assessment_id}`}
                          className="text-brand hover:underline font-semibold"
                        >
                          {item.assessment_id.slice(0, 8)}…
                        </Link>
                      </td>
                      <td className="py-2.5">
                        <GateBadge gate={item.quality_gate} />
                      </td>
                      <td className="py-2.5 mono text-right">
                        {formatScore(item.dq_score)}
                      </td>
                      <td className="py-2.5 mono text-right">
                        {formatRatio(item.coverage_ratio)}
                      </td>
                      <td className="py-2.5">
                        <PublicationBadge status={item.publication_status} />
                      </td>
                      <td className="py-2.5 text-xs text-fg-muted">
                        {formatTimestamp(item.created_at, lang).local}
                      </td>
                      <td className="py-2.5 text-right">
                        <Link
                          to={`/assessments/${item.assessment_id}`}
                          className="btn-secondary text-xs px-2.5 py-1"
                        >
                          {t("assessments.open_scorecard")}
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Pagination Controls */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
            <p className="text-xs text-fg-muted">
              {t("assessments.pagination_info", { page, count: total })}
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="btn-secondary text-xs px-2.5 py-1"
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
              >
                {t("common.previous")}
              </button>
              <button
                type="button"
                className="btn-secondary text-xs px-2.5 py-1"
                disabled={page * 25 >= total}
                onClick={() => setPage(page + 1)}
              >
                {t("common.next")}
              </button>
            </div>
          </div>
        </section>
      )}

      {/* Direct UUID lookup tool */}
      <section className="card space-y-3 max-w-xl">
        <h2 className="text-sm font-semibold">{t("assessments.direct_lookup")}</h2>
        <IdLookup label={t("assessments.col_id")} to={(id) => `/assessments/${id}`} />
      </section>
    </div>
  );
}

export function ScorecardPage() {
  const { t: rawT } = useI18n();
  const t = rawT as (key: PageKey, params?: Record<string, string | number>) => string;
  const { assessmentId = "" } = useParams();
  const query = useQuery({
    queryKey: ["assessment", assessmentId],
    queryFn: ({ signal }) => getAssessment(assessmentId, signal),
  });
  const a = query.data;

  useEffect(() => {
    if (a) recent.remember({ kind: "assessment", id: a.assessment_id, label: `Assessment ${a.assessment_id.slice(0, 8)}`, status: a.quality_gate });
  }, [a]);

  if (!a) {
    if (query.isError) return <ProblemAlert error={query.error} onRetry={() => query.refetch()} />;
    return <p aria-busy>{t("common.loading")}</p>;
  }

  return (
    <div className="space-y-6">
      <nav aria-label={t("scorecard.breadcrumb")} className="text-sm text-fg-muted">
        <Link to="/assessments" className="hover:underline">{t("nav.assessments")}</Link> / {t("scorecard.title")}
      </nav>
      <PageHeader
        title={t("scorecard.title")}
        actions={
          a.publication_status === "PUBLISHED" && (
            <Link to={`/public/assessments/${a.assessment_id}`} className="btn-secondary" target="_blank" rel="noopener">
              {t("scorecard.public_view")} <ExternalLink aria-hidden className="size-4" />
            </Link>
          )
        }
      />
      <ScoreHeader a={a} />
      <DimensionTiles dimensions={a.dimension_results} rules={a.rule_results} />
      <RuleTable rules={a.rule_results} />
      <section className="card" aria-labelledby="provenance">
        <h2 id="provenance" className="mb-3">{t("scorecard.provenance")}</h2>
        <dl className="grid gap-4 sm:grid-cols-2">
          <CopyId label={t("scorecard.assessment_id")} value={a.assessment_id} />
          <CopyId label={t("scorecard.assessment_hash")} value={a.assessment_hash} />
          <CopyId label={t("scorecard.run_id")} value={a.run_id} />
          <CopyId label={t("scorecard.snapshot_id")} value={a.snapshot_id} />
        </dl>
      </section>
    </div>
  );
}
