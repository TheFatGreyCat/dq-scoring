import { useMutation } from "@tanstack/react-query";
import { BadgeCheck, Check, Send, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { GovernanceStatus } from "../../api/types";
import { approve, submitForApproval, type GovernanceKind } from "../../api/endpoints";
import { ConfirmButton } from "../../components/ConfirmButton";
import { Field } from "../../components/Field";
import { isUuid } from "../../components/IdLookup";
import { ProblemAlert } from "../../components/ProblemAlert";
import { GovernanceBadge } from "../../components/StatusBadge";
import { useI18n } from "../../lib/i18n";
import { recent, useRecent, type RecentKind } from "../../lib/recent";

const STAGES: GovernanceStatus[] = ["DRAFT", "PENDING_APPROVAL", "ACTIVE"];
export function StageTrack({ status }: { status: GovernanceStatus }) {
  const { t } = useI18n();
  const current = STAGES.indexOf(status);
  const stageLabels: Record<string, string> = {
    DRAFT: t("status.DRAFT"),
    PENDING_APPROVAL: t("status.PENDING_APPROVAL"),
    ACTIVE: t("status.ACTIVE"),
  };
  return (
    <ol className="flex flex-wrap items-center gap-2 text-sm" aria-label={t("gov.approval.stage_label")}>
      {STAGES.map((stage, i) => {
        const done = current >= 0 && i < current;
        const active = i === current;
        return (
          <li key={stage} className="flex items-center gap-2" aria-current={active ? "step" : undefined}>
            <span
              className={`grid place-items-center size-6 rounded-full text-xs font-bold border ${
                active ? "bg-action text-on-action border-action" : done ? "bg-pass-bg text-pass border-pass" : "border-border text-fg-muted"
              }`}
            >
              {done ? <Check aria-hidden className="size-3.5" /> : i + 1}
            </span>
            <span className={active ? "font-semibold" : "text-fg-muted"}>{stageLabels[stage] || stage}</span>
            {i < STAGES.length - 1 && <span aria-hidden className="w-6 h-px bg-border" />}
          </li>
        );
      })}
    </ol>
  );
}

interface Revision {
  status: GovernanceStatus;
  name: string;
  current_version: number;
  can_self_approve?: boolean;
}

const MAX_SELF_APPROVAL_REASON = 500;

/**
 * Submit / approve by ID. Approval normally needs a different authorized user (server returns 403 otherwise).
 * A WORKSPACE_ADMIN who created/submitted a ruleset or policy may instead self-approve through a separate
 * dialog with a mandatory reason; the server decides eligibility (`can_self_approve`), the UI only mirrors it.
 */
export function ApprovalPanel<T extends Revision>({
  kind,
  recentKind,
  idOf,
  noun,
  selectedEntity,
  serverItems = [],
  onActionSuccess,
}: {
  kind: GovernanceKind;
  recentKind: RecentKind;
  idOf: (entity: T) => string;
  noun: string;
  selectedEntity?: T | null;
  serverItems?: Array<{ id: string; label: string; status: GovernanceStatus; canSelfApprove?: boolean }>;
  onActionSuccess?: (entity: T) => void;
}) {
  const { t } = useI18n();
  const known = useRecent(recentKind);
  const [entityId, setEntityId] = useState(known[0]?.id ?? "");
  const [notes, setNotes] = useState("");
  const [result, setResult] = useState<T | null>(null);
  const [lastAction, setLastAction] = useState<"submitted" | "approved" | "self-approved" | null>(null);
  const [reason, setReason] = useState("");
  const selfDialog = useRef<HTMLDialogElement>(null);

  // Parents pass inline `idOf`; read it through a ref so only a new selection resets local state.
  const idOfRef = useRef(idOf);
  idOfRef.current = idOf;
  useEffect(() => {
    if (!selectedEntity) return;
    setEntityId(idOfRef.current(selectedEntity));
    setResult(selectedEntity);
    setLastAction(null);
  }, [selectedEntity]);

  useEffect(() => {
    if (selectedEntity || entityId) return;
    if (serverItems.length > 0) setEntityId(serverItems[0].id);
    else if (known.length > 0) setEntityId(known[0].id);
  }, [selectedEntity, serverItems, known, entityId]);
  const selectedIdRef = useRef(entityId.trim());
  selectedIdRef.current = entityId.trim();

  const onSuccess = (action: "submitted" | "approved" | "self-approved") => (entity: T) => {
    if (idOfRef.current(entity) === selectedIdRef.current) {
      setResult(entity);
      setLastAction(action);
      setNotes("");
      onActionSuccess?.(entity);
    }
    const label =
      serverItems.find((s) => s.id === idOf(entity))?.label ??
      known.find((k) => k.id === idOf(entity))?.label ??
      entity.name;
    recent.remember({ kind: recentKind, id: idOf(entity), label, status: entity.status });
  };
  const submit = useMutation({ mutationFn: () => submitForApproval<T>(kind, entityId.trim(), notes), onSuccess: onSuccess("submitted") });
  const approval = useMutation({ mutationFn: () => approve<T>(kind, entityId.trim(), notes), onSuccess: onSuccess("approved") });
  const selfApproval = useMutation({
    mutationFn: (selfReason: string) => approve<T>(kind, entityId.trim(), notes, selfReason),
    onSuccess: (entity) => { setReason(""); onSuccess("self-approved")(entity); },
  });
  const error = submit.error ?? approval.error ?? selfApproval.error;
  const pending = submit.isPending || approval.isPending || selfApproval.isPending;
  const valid = isUuid(entityId);
  const knownItem =
    serverItems.find((s) => s.id === entityId.trim()) ??
    known.find((k) => k.id === entityId.trim());
  const selectedResult = result && idOf(result) === entityId.trim() ? result : null;
  const knownStatus = selectedResult?.status ?? knownItem?.status;
  const canSelfApprove = valid && (selectedResult ? selectedResult.can_self_approve : knownItem && "canSelfApprove" in knownItem && knownItem.canSelfApprove) === true;

  return (
    <section className="card space-y-4" aria-labelledby={`${kind}-approval`}>
      <h2 id={`${kind}-approval`}>{t("gov.approval.title")}</h2>
      {serverItems.length > 0 && (
        <Field label={t("gov.approval.select_item")}>
          {(id) => (
            <select
              id={id}
              className="input"
              value={entityId}
              onChange={(e) => {
                setEntityId(e.target.value);
                setResult(null);
                setLastAction(null);
                submit.reset();
                approval.reset();
                selfApproval.reset();
              }}
            >
              <option value="">{t("gov.approval.select_item")}</option>
              {serverItems.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label} ({item.status})
                </option>
              ))}
            </select>
          )}
        </Field>
      )}
      <Field label={t("gov.approval.id_label", { noun })} hint={t("gov.approval.id_hint")}>
        {(id, hint) => (
          <>
            <input id={id} aria-describedby={hint} list={`${kind}-known`} className="input mono" value={entityId}
              spellCheck={false} aria-invalid={entityId !== "" && !valid}
              onChange={(e) => { setEntityId(e.target.value); setResult(null); setLastAction(null); submit.reset(); approval.reset(); selfApproval.reset(); }} />
            <datalist id={`${kind}-known`}>
              {serverItems.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
              {known.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
            </datalist>
          </>
        )}
      </Field>
      <Field label={t("gov.approval.notes")}>
        {(id) => <textarea id={id} className="input min-h-20 py-2" value={notes} onChange={(e) => setNotes(e.target.value)} />}
      </Field>
      <div className="flex flex-wrap gap-2">
        <ConfirmButton
          variant="secondary"
          label={t("gov.approval.submit_btn")}
          icon={<Send aria-hidden className="size-4" />}
          title={t("gov.approval.confirm_submit_title", { noun })}
          body={<p>{t("gov.approval.confirm_submit_body")}</p>}
          confirmLabel={t("btn.submit")}
          disabled={!valid || pending}
          onConfirm={() => submit.mutate()}
        />
        <ConfirmButton
          label={t("gov.approval.approve_btn")}
          icon={<BadgeCheck aria-hidden className="size-4" />}
          title={t("gov.approval.confirm_approve_title", { noun })}
          body={<p>{t("gov.approval.confirm_approve_body")}</p>}
          confirmLabel={t("btn.approve")}
          disabled={!valid || pending || canSelfApprove}
          onConfirm={() => approval.mutate()}
        />
        {canSelfApprove && (
          <button type="button" className="btn-secondary" disabled={pending} onClick={() => selfDialog.current?.showModal()}>
            <ShieldAlert aria-hidden className="size-4" />
            {t("gov.approval.self_btn")}
          </button>
        )}
      </div>

      <dialog
        ref={selfDialog}
        aria-labelledby={`${kind}-self-title`}
        className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-card bg-surface text-fg p-0 shadow-card backdrop:bg-black/50"
      >
        <form
          className="p-6 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!reason.trim()) return;
            selfApproval.mutate(reason.trim());
            selfDialog.current?.close();
          }}
        >
          <h2 id={`${kind}-self-title`}>{t("gov.approval.self_title", { noun })}</h2>
          <p className="text-sm text-warn" role="note">{t("gov.approval.self_warning")}</p>
          <Field label={t("gov.approval.self_reason")} hint={t("gov.approval.self_reason_hint", { max: MAX_SELF_APPROVAL_REASON })}>
            {(id, hint) => (
              <textarea id={id} aria-describedby={hint} required maxLength={MAX_SELF_APPROVAL_REASON} className="input min-h-24 py-2"
                value={reason} onChange={(e) => setReason(e.target.value)} />
            )}
          </Field>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-secondary" autoFocus onClick={() => selfDialog.current?.close()}>{t("btn.cancel")}</button>
            <button type="submit" className="btn-primary" disabled={!reason.trim()}>{t("gov.approval.self_confirm")}</button>
          </div>
        </form>
      </dialog>
      <ProblemAlert error={error} />

      {knownStatus && (
        <div role="status" aria-live="polite" className="space-y-3 rounded-control border border-border p-4">
          {lastAction && (
            <p className="font-semibold text-pass">
              {t(lastAction === "submitted" ? "gov.approval.submitted_success" : lastAction === "self-approved" ? "gov.approval.self_success" : "gov.approval.approved_success")}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            {knownItem && <span className="font-semibold">{knownItem.label}</span>}
            {selectedResult && <span className="text-sm text-fg-muted">v{selectedResult.current_version}</span>}
            <GovernanceBadge status={knownStatus} />
          </div>
          <StageTrack status={knownStatus} />
        </div>
      )}
      <p className="text-xs text-fg-muted">
        {t("gov.approval.four_eyes_notice")}
      </p>
    </section>
  );
}
