import { useMutation } from "@tanstack/react-query";
import { Bot } from "lucide-react";
import { useState } from "react";
import { createAiRecommendations } from "../../api/endpoints";
import type { AiEngine, AiPriority, AiRecommendations, QualityRuleInput } from "../../api/types";
import { ProblemAlert } from "../../components/ProblemAlert";
import { formatTimestamp } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { useAiGeneration } from "./useAiGeneration";

const PRIORITIES: AiPriority[] = ["COMPLETENESS", "VALIDITY", "UNIQUENESS"];

/**
 * Optional, explicit AI rule suggestions. Never runs on mount; adopted items only enter the
 * caller's editable DRAFT form (via onMerge) and never reach approval/ACTIVE from here.
 * Parent must remount (key) this panel when the snapshot changes.
 */
export function AiRecommendationsPanel({ snapshotId, onMerge }: { snapshotId: string; onMerge: (rules: QualityRuleInput[]) => void }) {
  const { lang, t } = useI18n();
  const { canGenerate, model } = useAiGeneration("recommendations");
  const [engine, setEngine] = useState<AiEngine>("HYBRID");
  const [priorities, setPriorities] = useState<AiPriority[]>(PRIORITIES);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const mutation = useMutation({
    mutationFn: () => createAiRecommendations(snapshotId, { engine, domain: "GENERAL", priorities }),
    onMutate: () => setSelected(new Set()),
  });

  if (!canGenerate) return null;

  const result: AiRecommendations | undefined = mutation.data;
  const toggle = (i: number, on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(i);
      else next.delete(i);
      return next;
    });

  return (
    <div className="rounded-control border border-border bg-surface-muted/40 p-4 space-y-3" aria-labelledby="ai-rec-title">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="ai-rec-title" className="font-semibold text-sm flex items-center gap-2">
          <Bot className="size-4 text-brand" aria-hidden /> {t("ai.rec.title")}
        </h3>
        <span className="rounded-control border border-border px-2 py-0.5 text-xs text-fg-muted">{t("ai.badge")}</span>
      </div>
      <p className="text-xs text-fg-muted">{t("ai.rec.desc")}</p>
      <p className="text-xs text-fg-muted">{t("ai.cost_notice")}</p>

      <div className="flex flex-wrap items-end gap-4 text-xs">
        <label className="space-y-1">
          <span className="block font-medium">{t("ai.rec.engine")}</span>
          <select className="input" value={engine} onChange={(e) => setEngine(e.target.value as AiEngine)}>
            <option value="HYBRID">{t("ai.rec.engine_hybrid")}</option>
            <option value="LLM">{t("ai.rec.engine_llm")}</option>
          </select>
        </label>
        <fieldset className="space-y-1">
          <legend className="font-medium">{t("ai.rec.priorities")}</legend>
          <div className="flex gap-3">
            {PRIORITIES.map((p) => (
              <label key={p} className="flex items-center gap-1">
                <input
                  type="checkbox"
                  className="size-4 accent-[var(--action)]"
                  checked={priorities.includes(p)}
                  onChange={(e) => setPriorities((prev) => (e.target.checked ? [...prev, p] : prev.filter((x) => x !== p)))}
                />
                {t(`ai.rec.priority.${p}`)}
              </label>
            ))}
          </div>
        </fieldset>
        <button type="button" className="btn-secondary text-xs" disabled={mutation.isPending || priorities.length === 0} onClick={() => mutation.mutate()}>
          {mutation.isPending ? t("ai.rec.generating") : t("ai.rec.generate")}
        </button>
      </div>

      <ProblemAlert error={mutation.error} />

      {result && (
        <div className="space-y-2" role="region" aria-live="polite">
          <p className="text-xs">
            {t("ai.rec.provenance", {
              source: t(`ai.rec.source.${result.provenance.source}`),
              model: result.provenance.model ?? model ?? "—",
              time: formatTimestamp(result.provenance.generated_at, lang).local,
            })}
          </p>
          <p className="text-xs text-fg-muted">
            {t("ai.rec.counts", { columns: result.provenance.columns_sent, rejected: result.provenance.candidates_rejected })}
          </p>
          {result.provenance.fallback && (
            <p role="status" className="text-xs text-warn">
              {t("ai.rec.fallback", { code: result.provenance.fallback_code ?? "UNKNOWN" })}
            </p>
          )}
          {result.warnings?.map((w) => (
            <p key={w} className="text-xs text-warn">{w}</p>
          ))}
          <p className="text-xs text-fg-muted">{t("ai.rec.sample_disclaimer")}</p>

          {result.rules.length === 0 ? (
            <p className="text-xs">{t("ai.rec.empty")}</p>
          ) : (
            <>
              <ul className="max-h-48 overflow-y-auto space-y-2 border border-border rounded-control p-2 bg-surface">
                {result.rules.map((item, i) => (
                  <li key={i}>
                    <label className="flex items-start gap-2 text-xs p-1.5 rounded hover:bg-surface-muted cursor-pointer">
                      <input
                        type="checkbox"
                        className="size-4 mt-0.5 accent-[var(--action)]"
                        checked={selected.has(i)}
                        onChange={(e) => toggle(i, e.target.checked)}
                      />
                      <span className="flex-1">
                        <span className="flex flex-wrap items-center gap-2 font-mono">
                          <span className="font-semibold">{item.rule.rule_code}</span>
                          <span className="text-fg-muted">[{item.rule.dimension}]</span>
                          <span>{String(item.rule.parameters?.column ?? "")}</span>
                        </span>
                        <span className="block text-[11px] text-fg-muted">
                          {t("ai.rec.item_source", { source: item.source })}
                        </span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
              <div className="flex flex-wrap gap-2">
                <button type="button" className="btn-secondary text-xs" onClick={() => setSelected(new Set(result.rules.keys()))}>
                  {t("ai.rec.select_all")}
                </button>
                <button type="button" className="btn-secondary text-xs" onClick={() => setSelected(new Set())}>
                  {t("ai.rec.deselect_all")}
                </button>
                <button
                  type="button"
                  className="btn-primary text-xs"
                  disabled={selected.size === 0}
                  onClick={() => {
                    onMerge(result.rules.filter((_, i) => selected.has(i)).map((r) => r.rule));
                    setSelected(new Set());
                  }}
                >
                  {t("ai.rec.merge", { count: selected.size })}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
