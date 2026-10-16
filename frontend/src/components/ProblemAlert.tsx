import { CircleAlert, RefreshCw } from "lucide-react";
import { ApiError } from "../api/client";
import { useI18n, type TranslationKey } from "../lib/i18n";
import type { SurfaceTranslationKey } from "../lib/surfaceTranslations";

export type TranslateFn = (
  key: TranslationKey | SurfaceTranslationKey,
  params?: Record<string, string | number>,
) => string;

/** Safe, user-facing message per failure class (APPLICATION_UI_DESIGN §4). */
export function describeError(
  error: unknown,
  t?: TranslateFn,
): { title: string; detail?: string } {
  if (!(error instanceof ApiError)) {
    return { title: t ? t("error.generic") : "Something went wrong." };
  }
  if (error.kind === "timeout") {
    return {
      title: t ? t("error.timeout_title") : "No response in time.",
      detail: t ? t("error.timeout_detail") : "The outcome is unknown. Check status before retrying.",
    };
  }
  if (error.kind === "network") {
    return {
      title: t ? t("error.network_title") : "Cannot reach the server.",
      detail: t ? t("error.network_detail") : "Check your connection and try again.",
    };
  }

  const errorCode = error.problem?.error_code ?? error.problem?.reason;
  if (errorCode && t) {
    const errorKey = `error.${errorCode}` as TranslationKey | SurfaceTranslationKey;
    try {
      const translated = t(errorKey);
      if (translated && translated !== errorKey) {
        return { title: translated, detail: error.problem?.detail };
      }
    } catch {
      // not in dictionary
    }
  }

  const detail = error.problem?.detail;
  switch (error.status) {
    case 401:
      return {
        title: t ? t("error.401_title") : "Your session has ended.",
        detail: t ? t("error.401_detail") : "Sign in again to continue.",
      };
    case 403:
      return {
        title: t ? t("error.403_title") : "You do not have access to this action.",
        detail: detail ?? (t ? t("error.403_detail") : undefined),
      };
    case 404:
      return {
        title: t ? t("error.404_title") : "Not available.",
        detail: detail ?? (t ? t("error.404_detail") : "This item does not exist or is not visible to you."),
      };
    case 409:
      return {
        title: t ? t("error.409_title") : "This item changed since you loaded it.",
        detail: detail ?? (t ? t("error.409_detail") : undefined),
      };
    case 400:
    case 422:
      return {
        title: t ? t("error.422_title") : "Please check the highlighted values.",
        detail,
      };
    default:
      return {
        title: t ? t("error.server_error_title") : "The server could not complete the request.",
        detail: error.problem?.instance ? `Reference: ${error.problem.instance}` : undefined,
      };
  }
}
export function ProblemAlert({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null;
  const { t } = useI18n();
  const { title, detail } = describeError(error, t);
  const fieldErrors = error instanceof ApiError ? (error.problem?.invalid_params ?? []) : [];
  return (
    <div role="alert" className="flex gap-3 rounded-control border border-fail/30 bg-fail-bg p-4 text-fail">
      <CircleAlert aria-hidden className="size-5 shrink-0 mt-0.5" />
      <div className="flex-1 space-y-1 text-sm">
        <p className="font-semibold">{title}</p>
        {detail && <p>{detail}</p>}
        {fieldErrors.length > 0 && (
          <ul className="list-disc pl-5">
            {fieldErrors.map((f) => {
              let reason = f.reason;
              if (f.code) {
                const codeKey = `error.${f.code}` as TranslationKey | SurfaceTranslationKey;
                try {
                  const translatedReason = t(codeKey, f.params as Record<string, string | number> | undefined);
                  if (translatedReason && translatedReason !== codeKey) {
                    reason = translatedReason;
                  }
                } catch {
                  // fallback to reason
                }
              }
              return (
                <li key={f.name}>
                  <span className="mono">{f.name.replace(/^body\./, "")}</span>: {reason}
                </li>
              );
            })}
          </ul>
        )}
      </div>
      {onRetry && (
        <button type="button" className="btn-secondary min-h-9 text-fg" onClick={onRetry}>
          <RefreshCw aria-hidden className="size-4" /> {t("common.retry")}
        </button>
      )}
    </div>
  );
}
