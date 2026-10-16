import { Info } from "lucide-react";
import type { DimensionResult, PublicationStatus, QualityGate, RuleResult } from "../../api/types";
import { DIMENSIONS } from "../../api/types";
import { GateBadge, PublicationBadge } from "../../components/StatusBadge";
import { EMPTY, formatRatio, formatScore, formatTimestamp } from "../../lib/format";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import type { SurfaceTranslationKey } from "../../lib/surfaceTranslations";

type ScoreKey = TranslationKey | SurfaceTranslationKey;

interface Summary {
  dq_score: number | null;
  coverage_ratio: number | null;
  publication_status: PublicationStatus;
  quality_gate: QualityGate;
  created_at: string;
}

export function ScoreHeader({ a }: { a: Summary }) {
  const { lang, t: rawT } = useI18n();
  const t = rawT as (key: ScoreKey, params?: Record<string, string | number>) => string;
  const created = formatTimestamp(a.created_at, lang);
  const withheld = a.publication_status === "WITHHELD";

  const withheldReason =
    a.quality_gate === "ERROR"
      ? t("scorecard.withheld_error")
      : a.quality_gate === "INSUFFICIENT_EVIDENCE"
        ? t("scorecard.withheld_insufficient")
        : t("scorecard.withheld_default");

  return (
    <section className="card space-y-4" aria-label={t("scorecard.summary_aria")}>
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <p className="text-sm text-fg-muted">{t("scorecard.dq_score")}</p>
          <p className="mono text-4xl font-semibold" data-testid="dq-score">
            {formatScore(a.dq_score)}
            {a.dq_score != null && <span className="text-base text-fg-muted"> / 100</span>}
          </p>
        </div>
        <div>
          <p className="text-sm text-fg-muted inline-flex items-center gap-1">
            {t("scorecard.coverage")}
            <Info aria-hidden className="size-3.5" />
          </p>
          <p className="mono text-2xl font-semibold">{formatRatio(a.coverage_ratio)}</p>
          <p className="text-xs text-fg-muted">{t("scorecard.coverage_desc")}</p>
        </div>
        <div className="space-y-2">
          <p className="text-sm text-fg-muted">{t("scorecard.quality_gate")}</p>
          <GateBadge gate={a.quality_gate} size="lg" />
        </div>
        <div className="space-y-2">
          <p className="text-sm text-fg-muted">{t("scorecard.publication")}</p>
          <PublicationBadge status={a.publication_status} />
          <p className="text-xs text-fg-muted" title={created.utc}>{t("scorecard.assessed_at", { time: created.local })}</p>
        </div>
      </div>
      {withheld && (
        <p className="rounded-control bg-neutral-bg p-3 text-sm text-neutral">
          <strong>{t("scorecard.score_withheld")}</strong> {withheldReason}
        </p>
      )}
    </section>
  );
}

function unscoredLabel(allRules: RuleResult[] | undefined, t: (key: ScoreKey) => string): string {
  if (!allRules) return t("scorecard.not_scored");
  // Advisory signals never contribute to a dimension, so they do not make it "measurable".
  const rules = allRules.filter((r) => !r.is_advisory);
  if (rules.length === 0) return t("scorecard.no_rules");
  return rules.every((r) => r.measurement_status === "NOT_APPLICABLE")
    ? t("scorecard.not_applicable")
    : t("scorecard.not_measurable");
}

/** Six dimension tiles; a null score is labelled, never shown as zero. */
export function DimensionTiles({ dimensions, rules }: { dimensions: DimensionResult[]; rules?: RuleResult[] }) {
  const { t: rawT } = useI18n();
  const t = rawT as (key: ScoreKey, params?: Record<string, string | number>) => string;
  const byName = new Map(dimensions.map((d) => [d.dimension.toUpperCase(), d]));
  return (
    <section aria-labelledby="dimensions">
      <h2 id="dimensions" className="mb-3">{t("scorecard.dimensions")}</h2>
      <ul className="grid gap-4 grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {DIMENSIONS.map((name) => {
          const d = byName.get(name);
          const score = d?.dimension_score ?? null;
          const dimRules = rules?.filter((r) => r.dimension.toUpperCase() === name);
          return (
            <li key={name} className="card p-4 space-y-1">
              <p className="text-sm font-medium">{t(`dim.${name}`)}</p>
              {score == null ? (
                <p className="text-sm font-semibold text-neutral py-1.5">{unscoredLabel(dimRules, t)}</p>
              ) : (
                <p className="mono text-2xl font-semibold">{formatScore(score)}</p>
              )}
              <p className="text-xs text-fg-muted">
                {t("scorecard.coverage_label", { ratio: d ? formatRatio(d.coverage_ratio) : EMPTY })}
              </p>
              {score != null && (
                <div aria-hidden className="h-1.5 rounded-full bg-surface-muted overflow-hidden">
                  <div className="h-full bg-fg-muted" style={{ width: `${Math.max(0, Math.min(100, score))}%` }} />
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
