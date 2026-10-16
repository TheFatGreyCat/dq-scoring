import { useMutation } from "@tanstack/react-query";
import { Globe, LogIn } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";
import { ApiError } from "../../api/client";
import { login } from "../../api/endpoints";
import { BrandMark } from "../../app/BrandMark";
import { Field } from "../../components/Field";
import { ProblemAlert } from "../../components/ProblemAlert";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import type { SurfaceTranslationKey } from "../../lib/surfaceTranslations";
import { FALLBACK_LOCK_SECONDS, LockoutDialog } from "./LockoutDialog";
import { useSession } from "./useSession";

export function LoginPage() {
  const { authenticated } = useSession();
  const { lang, toggleLang, t: rawT } = useI18n();
  const t = rawT as (key: TranslationKey | SurfaceTranslationKey) => string;
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tenantId, setTenantId] = useState("");

  const mutation = useMutation({
    mutationFn: () => login(email.trim(), password, tenantId.trim() || undefined),
    onSuccess: () => navigate(from, { replace: true }),
    onSettled: () => setPassword(""),
  });

  if (authenticated && !mutation.isPending) return <Navigate to={from} replace />;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    mutation.mutate();
  };

  const credentialError =
    mutation.error instanceof ApiError && (mutation.error.status === 401 || mutation.error.status === 403);

  const lockout = mutation.error instanceof ApiError && mutation.error.status === 423 ? mutation.error : null;

  return (
    <div className="min-h-dvh grid place-items-center bg-bg px-4 py-8">
      <div className="w-full max-w-md">
        <div className="h-1.5 rounded-t-card bg-brand" aria-hidden />
        <form onSubmit={submit} className="card rounded-t-none space-y-5" noValidate>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <BrandMark />
              <div>
                <h1 className="text-xl font-bold">{t("auth.title")}</h1>
                <p className="text-xs text-fg-muted">{t("auth.subtitle")}</p>
              </div>
            </div>

            <button
              type="button"
              onClick={toggleLang}
              className="flex items-center gap-1 px-2.5 py-1 rounded-control border border-border hover:bg-surface-muted text-xs font-semibold cursor-pointer shadow-xs"
              title={t("auth.lang_switch")}
            >
              <Globe className="size-3.5 text-brand" />
              <span>{lang.toUpperCase()}</span>
            </button>
          </div>

          {mutation.isError && !lockout &&
            (credentialError ? (
              <div role="alert" className="rounded-control bg-fail-bg p-3 text-sm text-fail font-medium space-y-1">
                <p>{t("auth.invalid_credentials")}</p>
                <p className="text-xs text-fail/85 font-normal">
                  {t("auth.workspace_hint")}
                </p>
              </div>
            ) : (
              <ProblemAlert error={mutation.error} />
            ))}

          <Field label={t("auth.email")}>
            {(id) => (
              <input
                id={id}
                className="input"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            )}
          </Field>

          <Field label={t("auth.password")}>
            {(id) => (
              <input
                id={id}
                className="input"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            )}
          </Field>

          <Field
            label={t("auth.workspace_id")}
            hint={t("auth.workspace_desc")}
          >
            {(id, hint) => (
              <input
                id={id}
                aria-describedby={hint}
                className="input mono text-sm"
                placeholder={t("auth.workspace_placeholder")}
                spellCheck={false}
                onChange={(e) => setTenantId(e.target.value)}
              />
            )}
          </Field>

          <button
            type="submit"
            className="btn-primary w-full cursor-pointer shadow-xs"
            disabled={mutation.isPending || !email || !password}
          >
            <LogIn aria-hidden className="size-4" />
            {mutation.isPending ? t("auth.signing_in") : t("auth.sign_in")}
          </button>
        </form>

        {lockout && (
          <LockoutDialog
            userName={email.trim()}
            retryAfterSeconds={lockout.problem?.retry_after_seconds ?? FALLBACK_LOCK_SECONDS}
            maxAttempts={lockout.problem?.max_failed_attempts}
            onExpired={mutation.reset}
          />
        )}
      </div>
    </div>
  );
}
