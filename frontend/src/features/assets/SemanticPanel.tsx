import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { ApiError, session } from "../../api/client";
import { confirmSemantics, getSemantics, inferSemantics } from "../../api/endpoints";
import { SEMANTIC_LABELS, type ProfileMode, type SemanticLabel, type SemanticProvider, type UUID } from "../../api/types";
import { ProblemAlert } from "../../components/ProblemAlert";
import { useI18n } from "../../lib/i18n";
import { IMPORT_ROLES, useIdentity } from "../auth/useIdentity";

const MODES: ProfileMode[] = ["SAMPLE", "FULL"];
const PROVIDERS: SemanticProvider[] = ["LOCAL", "API"];
const MAX_REASON = 500;
const errorCode = (e: unknown) => (e instanceof ApiError ? e.problem?.error_code : undefined);

/** Staged value: a label to confirm, or null to reset. Nothing is saved until the user confirms. */
type Staged = Record<string, SemanticLabel | null>;

export function SemanticPanel({ snapshotId }: { snapshotId: UUID }) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const role = useIdentity().data?.role;
  const [mode, setMode] = useState<ProfileMode>("SAMPLE");
  const [provider, setProvider] = useState<SemanticProvider>("LOCAL");
  const [staged, setStaged] = useState<Staged>({});
  const [reason, setReason] = useState("");
  const [saved, setSaved] = useState<{ count: number; revision: number } | null>(null);
  const abort = useRef<AbortController | null>(null);

  const queryKey = ["semantics", session.email(), snapshotId, mode];
  const view = useQuery({ queryKey, queryFn: ({ signal }) => getSemantics(snapshotId, mode, signal) });

  const confirm = useMutation({
    mutationFn: () =>
      confirmSemantics(snapshotId, {
        expected_revision: view.data!.revision,
        reason: reason.trim(),
        changes: Object.entries(staged).map(([column, label]) => ({ column, label })),
      }),
    onSuccess: (r) => {
      setSaved({ count: r.changed, revision: r.revision });
      setStaged({});
      setReason("");
    },
    onError: (e) => {
      if (errorCode(e) === "SEMANTIC_REVISION_CONFLICT") void queryClient.invalidateQueries({ queryKey: ["semantics"] });
    },
    onSettled: (_d, e) => {
      if (!e) void queryClient.invalidateQueries({ queryKey: ["semantics"] });
    },
  });

  const infer = useMutation({
    mutationFn: () => {
      abort.current?.abort();
      abort.current = new AbortController();
      return inferSemantics(snapshotId, provider, mode, abort.current.signal);
    },
  });

  const changeSelection = (apply: () => void) => {
    abort.current?.abort();
    infer.reset();
    apply();
  };

  const forbidden = confirm.error instanceof ApiError && confirm.error.status === 403;
  const canWrite = !!role && !!IMPORT_ROLES[role] && !forbidden;
  const data = view.data;
  const candidates = new Map(infer.data?.candidates.map((c) => [c.column, c]));
  const stagedCount = Object.keys(staged).length;
  const canConfirm = canWrite && stagedCount > 0 && reason.trim().length > 0 && reason.length <= MAX_REASON && !confirm.isPending;

  const stage = (column: string, label: SemanticLabel | "", confirmed: SemanticLabel | undefined) =>
    setStaged((prev) => {
      const rest = { ...prev };
      delete rest[column];
      const next = label === "" ? (confirmed ? null : undefined) : label === confirmed ? undefined : label;
      return next === undefined ? rest : { ...rest, [column]: next };
    });

  return (
    <section className="space-y-4" aria-labelledby="semantic-title">
      <div>
        <h2 id="semantic-title" className="text-lg font-semibold">{t("semantic.title")}</h2>
        <p className="text-sm text-fg-muted">{t("semantic.desc")}</p>
      </div>

      <div className="flex flex-wrap items-end gap-4 text-sm">
        <label className="space-y-1">
          <span className="block font-medium">{t("semantic.mode")}</span>
          <select className="input min-h-11" value={mode} onChange={(e) => changeSelection(() => setMode(e.target.value as ProfileMode))}>
            {MODES.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </label>
        <fieldset className="space-y-1">
          <legend className="font-medium">{t("semantic.provider")}</legend>
          <div className="flex gap-4">
            {PROVIDERS.map((p) => (
              <label key={p} className="flex min-h-11 items-center gap-2">
                <input
                  type="radio"
                  name="semantic-provider"
                  className="size-4 accent-[var(--action)]"
                  checked={provider === p}
                  onChange={() => changeSelection(() => setProvider(p))}
                />
                {t(`semantic.provider.${p}`)}
              </label>
            ))}
          </div>
        </fieldset>
        <button type="button" className="btn-secondary min-h-11" disabled={infer.isPending || !canWrite || !data} onClick={() => infer.mutate()}>
          {infer.isPending ? t("semantic.suggesting") : t("semantic.suggest")}
        </button>
      </div>
      <p className="text-xs text-fg-muted">{t("semantic.provider_note")}</p>
      {!canWrite && <p className="text-xs text-fg-muted">{t("semantic.read_only")}</p>}

      <div role="region" aria-live="polite" className="min-h-6 space-y-2">
        {errorCode(infer.error) === "AI_CONTEXT_STALE" ? (
          <p className="text-sm text-warn">{t("semantic.discarded_stale")}</p>
        ) : (
          <ProblemAlert error={infer.error} />
        )}
        {infer.data && (
          <p className="text-xs">
            {t("semantic.inference_meta", { provider: infer.data.provenance.provider, mode: infer.data.provenance.profile.mode, rejected: infer.data.rejected })}
          </p>
        )}
        {saved && <p className="text-sm text-fg">{t("semantic.confirmed_ok", saved)}</p>}
      </div>

      <ProblemAlert error={view.error} onRetry={() => void view.refetch()} />
      {view.isLoading && <p className="text-sm text-fg-muted">{t("semantic.loading")}</p>}

      {data && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-fg-muted">
                <th scope="col" className="p-2">{t("semantic.col.column")}</th>
                <th scope="col" className="p-2">{t("semantic.col.evidence")}</th>
                <th scope="col" className="p-2">{t("semantic.col.candidate")}</th>
                <th scope="col" className="p-2">{t("semantic.col.confirmed")}</th>
              </tr>
            </thead>
            <tbody>
              {data.columns.map((c) => {
                const candidate = candidates.get(c.column);
                const value = c.column in staged ? (staged[c.column] ?? "") : (c.confirmed?.label ?? "");
                return (
                  <tr key={c.column} className="border-t border-border align-top">
                    <th scope="row" className="p-2 text-left font-mono font-normal">
                      {c.column}
                      {c.protected && <span className="block text-xs text-warn">{t("semantic.protected")}</span>}
                    </th>
                    <td className="p-2">
                      <span className="block">{t(`semantic.label.${c.suggested_label}`)}</span>
                      <span className="block text-xs text-fg-muted">
                        {t("semantic.evidence_note")} · {t("semantic.confidence", { value: Math.round(c.confidence * 100) })}
                      </span>
                      <span className="block break-words font-mono text-[11px] text-fg-muted">{c.reason_codes.join(", ")}</span>
                    </td>
                    <td className="p-2">
                      {candidate && (
                        <>
                          <span className="block">{t(`semantic.label.${candidate.label}`)}</span>
                          <button
                            type="button"
                            className="btn-secondary min-h-11 text-xs"
                            disabled={!canWrite}
                            onClick={() => stage(c.column, candidate.label, c.confirmed?.label)}
                          >
                            {t("semantic.use_suggestion")}
                          </button>
                        </>
                      )}
                    </td>
                    <td className="p-2">
                      <select
                        className="input min-h-11"
                        aria-label={`${t("semantic.col.confirmed")}: ${c.column}`}
                        value={value}
                        disabled={!canWrite}
                        onChange={(e) => stage(c.column, e.target.value as SemanticLabel | "", c.confirmed?.label)}
                      >
                        <option value="">{t("semantic.unconfirmed")}</option>
                        {SEMANTIC_LABELS.map((l) => <option key={l} value={l}>{t(`semantic.label.${l}`)}</option>)}
                      </select>
                      {c.column in staged && <span className="block text-xs text-warn">{t("semantic.staged")}</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {canWrite && stagedCount > 0 && (
        <div className="space-y-2">
          <label className="block space-y-1 text-sm">
            <span className="block font-medium">{t("semantic.reason")}</span>
            <textarea className="input w-full" rows={2} maxLength={MAX_REASON} value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <ProblemAlert error={confirm.error} />
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-primary min-h-11" disabled={!canConfirm} onClick={() => confirm.mutate()}>
              {t("semantic.confirm", { count: stagedCount })}
            </button>
            <button type="button" className="btn-secondary min-h-11" onClick={() => setStaged({})}>
              {t("semantic.discard")}
            </button>
          </div>
        </div>
      )}
      {(stagedCount === 0 || !canWrite) && <ProblemAlert error={confirm.error} />}
    </section>
  );
}
