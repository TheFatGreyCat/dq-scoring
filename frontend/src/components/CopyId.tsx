import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { useI18n } from "../lib/i18n";

const COPIED_FEEDBACK_MS = 1500;

export function CopyId({ label, value }: { label: string; value: string }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), COPIED_FEEDBACK_MS);
  };
  return (
    <div className="min-w-0">
      <dt className="text-xs text-fg-muted">{label}</dt>
      <dd className="flex items-center gap-1">
        <span className="mono text-sm truncate" title={value}>
          {value}
        </span>
        <button
          type="button"
          onClick={copy}
          className="shrink-0 grid place-items-center size-11 rounded-control hover:bg-surface-muted cursor-pointer"
          aria-label={copied ? `${label} ${t("btn.copied")}` : `${t("btn.copy")} ${label}`}
        >
          {copied ? <Check aria-hidden className="size-4 text-pass" /> : <Copy aria-hidden className="size-4" />}
        </button>
      </dd>
    </div>
  );
}
