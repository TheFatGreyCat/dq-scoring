import { useId, useRef } from "react";
import { Link } from "react-router";
import { useI18n } from "../lib/i18n";
import { IMPORT_ROLES, useIdentity } from "../features/auth/useIdentity";

export function UsageGuide() {
  const dialog=useRef<HTMLDialogElement>(null);
  const title=useId();
  const {t}=useI18n();
  const identity=useIdentity();
  const importing=!!identity.data && !!IMPORT_ROLES[identity.data.role];
  return <><button className="btn-secondary" onClick={()=>dialog.current?.showModal()}>{t("guide.title")}</button><dialog ref={dialog} aria-labelledby={title} className="m-auto w-[min(42rem,calc(100vw-2rem))] max-h-[calc(100dvh-2rem)] overflow-y-auto rounded-card bg-surface text-fg p-6 backdrop:bg-black/50"><h2 id={title}>{t("guide.title")}</h2><div className="space-y-4 py-4"><p>{t(importing ? "guide.flow" : "guide.viewer")}</p><p>{t("guide.upload")}</p><p>{t("guide.recovery")}</p><p>{t("guide.approval")}</p><p>{t("guide.queue")}</p><Link className="text-action" to="/assets" onClick={()=>dialog.current?.close()}>{t("nav.assets")}</Link><Link className="ml-4 text-action" to="/runs" onClick={()=>dialog.current?.close()}>{t("nav.runs")}</Link></div><form method="dialog"><button className="btn-secondary" autoFocus>{t("components.cancel")}</button></form></dialog></>;
}
