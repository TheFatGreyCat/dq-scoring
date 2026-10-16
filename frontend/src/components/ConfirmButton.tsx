import { useId, useRef, type ReactNode } from "react";
import { useI18n } from "../lib/i18n";

/** Explicit confirmation using the native <dialog> (focus trap + Esc for free). */
export function ConfirmButton({
  label,
  title,
  body,
  confirmLabel,
  onConfirm,
  disabled,
  icon,
  variant = "primary",
}: {
  label: string;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  disabled?: boolean;
  icon?: ReactNode;
  variant?: "primary" | "secondary";
}) {
  const { t } = useI18n();
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  return (
    <>
      <button type="button" className={`btn-${variant}`} disabled={disabled} onClick={() => dialog.current?.showModal()}>
        {icon}
        {label}
      </button>
      <dialog
        ref={dialog}
        aria-labelledby={titleId}
        className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-card bg-surface text-fg p-0 shadow-card backdrop:bg-black/50"
      >
        <form method="dialog" className="p-6 space-y-4">
          <h2 id={titleId}>{title}</h2>
          <div className="text-sm text-fg-muted space-y-2">{body}</div>
          <div className="flex justify-end gap-2">
            <button value="cancel" className="btn-secondary" autoFocus>
              {t("btn.cancel")}
            </button>
            <button value="confirm" className="btn-primary" onClick={onConfirm}>
              {confirmLabel}
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}
