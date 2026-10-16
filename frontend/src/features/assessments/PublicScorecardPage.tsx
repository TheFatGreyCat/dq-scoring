import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router";
import { ApiError } from "../../api/client";
import { getPublicAssessment } from "../../api/endpoints";
import { BrandMark } from "../../app/BrandMark";
import { CopyId } from "../../components/CopyId";
import { ProblemAlert } from "../../components/ProblemAlert";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import type { SurfaceTranslationKey } from "../../lib/surfaceTranslations";
import { DimensionTiles, ScoreHeader } from "./ScoreSummary";

type PubKey = TranslationKey | SurfaceTranslationKey;
/** Calls only the public projection; never fetches private detail (AC-022). */
export function PublicScorecardPage() {
  const { t: rawT } = useI18n();
  const t = rawT as (key: PubKey) => string;
  const { assessmentId = "" } = useParams();
  const query = useQuery({
    queryKey: ["public-assessment", assessmentId],
    queryFn: ({ signal }) => getPublicAssessment(assessmentId, signal),
  });
  const a = query.data;
  const unavailable = query.error instanceof ApiError && (query.error.status === 404 || query.error.status === 403);

  return (
    <div className="min-h-dvh bg-bg">
      <div className="h-1 bg-brand" aria-hidden />
      <header className="flex items-center gap-3 h-16 px-4 sm:px-8 bg-surface border-b border-border">
        <BrandMark />
        <p className="font-bold">{t("scorecard.public_title")}</p>
      </header>
      <main className="max-w-6xl mx-auto p-4 sm:p-8 space-y-6">
        {query.isPending && <p aria-busy>{t("common.loading")}</p>}
        {unavailable && (
          <section className="card text-center py-12">
            <h1>{t("scorecard.unavailable_title")}</h1>
            <p className="mt-2 text-fg-muted">{t("scorecard.unavailable_desc")}</p>
          </section>
        )}
        {query.isError && !unavailable && <ProblemAlert error={query.error} onRetry={() => query.refetch()} />}
        {a && (
          <>
            <h1 className="sr-only">{t("scorecard.public_title")}</h1>
            <ScoreHeader a={a} />
            <DimensionTiles dimensions={a.dimensions} />
            <section className="card">
              <dl className="grid gap-4 sm:grid-cols-2">
                <CopyId label={t("scorecard.assessment_id")} value={a.assessment_id} />
                <CopyId label={t("scorecard.assessment_hash")} value={a.assessment_hash} />
              </dl>
            </section>
          </>
        )}
      </main>
    </div>
  );
}
