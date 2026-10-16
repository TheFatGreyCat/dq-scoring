import { useEffect, useRef, useState } from "react";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import type { SurfaceTranslationKey } from "../../lib/surfaceTranslations";

const TICK_MS = 1000;
export const FALLBACK_LOCK_SECONDS = 60; // 423 body without retry_after_seconds

const mmss = (seconds: number) =>
  `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;

export function LockoutDialog({ userName, retryAfterSeconds, maxAttempts, onExpired }: {
  userName: string;
  retryAfterSeconds: number;
  maxAttempts?: number;
  onExpired: () => void;
}) {
  const { t: rawT } = useI18n();
  const t = rawT as (key: TranslationKey | SurfaceTranslationKey, params?: Record<string, string | number>) => string;
  const ref = useRef<HTMLDialogElement>(null);
  const [deadline] = useState(() => Date.now() + retryAfterSeconds * 1000);
  const [now, setNow] = useState(Date.now);
  const remaining = Math.max(0, Math.ceil((deadline - now) / 1000));

  useEffect(() => {
    ref.current?.showModal();
    const timer = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (remaining === 0) onExpired();
  }, [remaining, onExpired]);

  return (
    <dialog ref={ref} aria-labelledby="lockout-title" onCancel={(e) => e.preventDefault()}
      className="lockout card m-auto w-full max-w-sm space-y-2 text-center">
      <h2 id="lockout-title" className="text-lg">{userName}</h2>
      <p role="timer" className="mono text-3xl text-fail">{mmss(remaining)}</p>
      <p className="text-sm text-fg-muted">{maxAttempts
          ? t("auth.lockout_attempts", { count: maxAttempts })
          : t("auth.lockout_generic")}</p>
    </dialog>
  );
}
