import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type MouseEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { session } from "../../api/client";
import { getPreview, getSnapshot } from "../../api/endpoints";
import { CopyId } from "../../components/CopyId";
import { PageHeader } from "../../components/Field";
import { ProblemAlert } from "../../components/ProblemAlert";
import { useI18n } from "../../lib/i18n";
import { PrivacyPanel, useColumnClassifications } from "./PrivacyPanel";
import { PrivacyRulesPanel } from "./PrivacyRulesPanel";
import { ProfilingPanel } from "./ProfilingPanel";

const VALID_TABS = ["overview", "classification", "detectors"] as const;
type TabType = (typeof VALID_TABS)[number];

export function SnapshotDetailPage() {
  const { t } = useI18n();
  const { snapshotId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();

  // Tab validation & normalization
  const rawTab = searchParams.get("tab");
  const tab: TabType = VALID_TABS.includes(rawTab as TabType)
    ? (rawTab as TabType)
    : "overview";

  useEffect(() => {
    if (rawTab && !VALID_TABS.includes(rawTab as TabType)) {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("tab", "overview");
          return next;
        },
        { replace: true }
      );
    }
  }, [rawTab, setSearchParams]);

  // Dirty draft tracking across tabs
  const [isDirty, setIsDirty] = useState(false);

  // Warn on browser reload / navigation when classification draft is dirty
  useEffect(() => {
    if (!isDirty) return;
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [isDirty]);

  // Snapshot Metadata Query
  const metadata = useQuery({
    queryKey: ["snapshot", session.email(), snapshotId],
    queryFn: ({ signal }) => getSnapshot(snapshotId, signal),
  });

  // Preview Query (shared across panels)
  const preview = useQuery({
    queryKey: ["preview", session.email(), snapshotId],
    queryFn: () => getPreview(snapshotId),
    retry: false,
  });

  // Classifications Query (shared across overview & classification tabs)
  const classifications = useColumnClassifications(snapshotId);

  const snapshot = metadata.data;

  if (!snapshot) {
    return metadata.isError ? (
      <ProblemAlert error={metadata.error} />
    ) : (
      <p aria-busy="true">{t("common.loading")}</p>
    );
  }

  // Column names list for rule scoping
  const rawSchemaCols = (snapshot.schema_definition?.columns ?? []) as (
    | { name: string }
    | string
  )[];
  const snapshotColumns = rawSchemaCols.map((c) => (typeof c === "string" ? c : c.name));

  const handleTabClick = (targetTab: TabType, e: MouseEvent<HTMLAnchorElement>) => {
    if (tab === targetTab) return;
    if (isDirty) {
      const confirmed = window.confirm(t("privacy.unsaved_warning"));
      if (!confirmed) {
        e.preventDefault();
        return;
      }
      setIsDirty(false);
    }
  };

  return (
    <div key={snapshot.snapshot_id} className="space-y-6">
      {/* 1. Header & Actions */}
      <PageHeader
        title={t("nav.assets")}
        description={snapshot.source_kind}
        actions={
          <Link className="btn-primary" to={`/runs/new?snapshot=${snapshotId}`}>
            {t("recommend.run")}
          </Link>
        }
      />

      <section className="card space-y-4">
        <dl className="grid gap-3 sm:grid-cols-2 text-sm">
          <CopyId label="Snapshot ID" value={snapshot.snapshot_id} />
          <CopyId label="Asset ID" value={snapshot.asset_id} />
        </dl>
        <p className="text-sm text-fg-muted">
          {t("preview.rows", { count: snapshot.total_rows })} ·{" "}
          {t("preview.columns", { count: snapshot.total_columns })}
        </p>
        <div className="flex flex-wrap gap-3">
          <Link className="btn-secondary text-xs" to={`/rulesets?snapshot=${snapshotId}`}>
            {t("recommend.rules")}
          </Link>
          <Link className="btn-secondary text-xs" to={`/policies?snapshot=${snapshotId}`}>
            {t("recommend.policy")}
          </Link>
          <Link className="btn-secondary text-xs" to={`/templates?snapshot=${snapshotId}`}>
            {t("nav.templates")}
          </Link>
        </div>
      </section>

      {/* 2. Navigation Tabs */}
      <nav
        className="flex border-b border-border space-x-6 text-sm font-medium"
        aria-label="Snapshot sections"
      >
        <Link
          to="?tab=overview"
          aria-current={tab === "overview" ? "page" : undefined}
          onClick={(e) => handleTabClick("overview", e)}
          className={`pb-3 border-b-2 transition-colors ${
            tab === "overview"
              ? "border-action text-action font-semibold"
              : "border-transparent text-fg-muted hover:text-fg hover:border-border"
          }`}
        >
          {t("privacy.tab.overview")}
        </Link>
        <Link
          to="?tab=classification"
          aria-current={tab === "classification" ? "page" : undefined}
          onClick={(e) => handleTabClick("classification", e)}
          className={`pb-3 border-b-2 transition-colors flex items-center gap-1.5 ${
            tab === "classification"
              ? "border-action text-action font-semibold"
              : "border-transparent text-fg-muted hover:text-fg hover:border-border"
          }`}
        >
          <span>{t("privacy.tab.classification")}</span>
          {isDirty && (
            <span className="inline-block size-2 rounded-full bg-amber-500" title="Unsaved changes" />
          )}
        </Link>
        <Link
          to="?tab=detectors"
          aria-current={tab === "detectors" ? "page" : undefined}
          onClick={(e) => handleTabClick("detectors", e)}
          className={`pb-3 border-b-2 transition-colors ${
            tab === "detectors"
              ? "border-action text-action font-semibold"
              : "border-transparent text-fg-muted hover:text-fg hover:border-border"
          }`}
        >
          {t("privacy.tab.detectors")}
        </Link>
      </nav>

      {/* 3. Tab Contents */}
      {tab === "overview" && (
        <ProfilingPanel
          snapshot={snapshot}
          classifications={classifications.data?.columns}
          previewData={preview.data}
          previewLoading={preview.isLoading}
          previewError={preview.error}
        />
      )}

      {tab === "classification" && (
        <PrivacyPanel
          assetId={snapshot.asset_id}
          snapshotId={snapshot.snapshot_id}
          onDirtyChange={setIsDirty}
        />
      )}

      {tab === "detectors" && (
        <PrivacyRulesPanel
          assetId={snapshot.asset_id}
          snapshotId={snapshot.snapshot_id}
          snapshotColumns={snapshotColumns}
        />
      )}
    </div>
  );
}
