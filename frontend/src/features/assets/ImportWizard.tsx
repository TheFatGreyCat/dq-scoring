import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { abortImport, completeImport, configureImport, createImport, getImport, listAssets, registerImport, storageObjects, uploadPart } from "../../api/endpoints";
import type { DatasetPreview as PreviewData, ImportSession, StorageObject } from "../../api/types";
import { Field } from "../../components/Field";
import { ProblemAlert } from "../../components/ProblemAlert";
import { DICTIONARY, useI18n, type TranslationKey } from "../../lib/i18n";
import { DatasetPreview } from "./DatasetPreview";
import { useIdentity } from "../auth/useIdentity";
import { ConfirmButton } from "../../components/ConfirmButton";

const TERMINAL: Record<string, true> = { VERIFIED: true, REGISTERED: true, REJECTED: true, ABORTED: true, FAILED: true };

export function ImportWizard() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const uploadId = params.get("import") ?? "";
  const client = useQueryClient();
  const identity = useIdentity();
  const ownerKey = [identity.data?.user_id, identity.data?.tenant_id];
  const request = useRef<{payload: string; id: string} | null>(null);
  const [assetId, setAssetId] = useState("");
  const [name, setName] = useState("");
  const [assetQuery, setAssetQuery] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [object, setObject] = useState<StorageObject | null>(null);
  const [mode, setMode] = useState("file");
  const [format, setFormat] = useState("CSV");
  const [delimiter, setDelimiter] = useState(",");
  const [prefix, setPrefix] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [uploaded, setUploaded] = useState(0);
  const [ack, setAck] = useState(false);
  const [mapping, setMapping] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const assets = useQuery({ queryKey: ["import-assets", ...ownerKey, assetQuery], queryFn: ({ signal }) => listAssets({ q: assetQuery, page_size: 100 }, signal) });
  const objects = useQuery({ queryKey: ["storage", ...ownerKey, prefix, token], queryFn: ({ signal }) => storageObjects({ prefix, continuation_token: token }, signal), enabled: mode === "object" });
  const session = useQuery({ queryKey: ["import", ...ownerKey, uploadId], queryFn: ({ signal }) => getImport(uploadId, signal), enabled: !!uploadId, retry: false, refetchIntervalInBackground: false, refetchInterval: query => query.state.data && !TERMINAL[query.state.data.status] ? 2000 : false });
  const state = session.data;
  const selectFile = (next: File | null) => {
    setFile(next);
    if (!next) return;
    const ext = next.name.split(".").pop()?.toLowerCase();
    if (!["csv", "parquet", "jsonl"].includes(ext ?? "")) { setFile(null); setError(new Error(t("import.unsupported"))); return; }
    setError(null);
    setFormat(ext!.toUpperCase());
    if (!name && !assetId) setName(next.name.replace(/\.[^.]+$/, ""));
  };
  const updateState = (value: ImportSession) => client.setQueryData(["import", ...ownerKey, value.upload_id], value);
  const transfer = async (current: ImportSession, selected: File) => {
    if (selected.size !== current.size_bytes || selected.name !== current.original_filename) throw new Error(t("import.resume"));
    const completed = new Set(current.completed_parts ?? []);
    let bytes = [...completed].reduce((sum, part) => sum + Math.min(current.part_size, current.size_bytes - (part - 1) * current.part_size), 0);
    setUploaded(bytes);
    controller.current = new AbortController();
    let next = 1;
    const send = async () => {
      while (next <= current.part_count) {
        const part = next++;
        if (completed.has(part)) continue;
        const chunk = selected.slice((part - 1) * current.part_size, part * current.part_size);
        await uploadPart(current.upload_id, part, chunk, controller.current!.signal);
        bytes += chunk.size;
        setUploaded(bytes);
      }
    };
    try { await Promise.all([send(), send()]); } catch (error) { controller.current.abort(); throw error; }
    const refreshed = await getImport(current.upload_id);
    if (refreshed.completed_part_details?.length !== current.part_count) throw new Error(t("import.resume"));
    updateState(await completeImport(current.upload_id, refreshed.completed_part_details));
  };
  const perform = async (action: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await action(); } catch (err) { setError(err); await client.invalidateQueries({ queryKey: ["import", uploadId] }); }
    finally { setBusy(false); }
  };
  const start = () => perform(async () => {
    if (uploadId && (session.isPending || session.isError)) return;
    let current = state;
    if (!current) {
      const source = mode === "object" ? object : null;
      if ((!file && !source) || (!assetId && !name.trim())) return;
      const payload = { ...(assetId ? { asset_id: assetId } : { asset_name: name.trim() }), format, original_filename: source ? source.key.split("/").pop() : file!.name, size_bytes: source ? source.size_bytes : file!.size, ...(source ? { source: { bucket: source.bucket, key: source.key } } : {}), csv_options: { delimiter, encoding: "utf-8" } };
      const fingerprint = JSON.stringify(payload);
      if (request.current?.payload !== fingerprint) request.current = {payload: fingerprint, id: crypto.randomUUID()};
      current = await createImport({ ...payload, client_request_id: request.current.id });
      setParams(previous => { previous.set("import", current!.upload_id); return previous; });
      updateState(current);
    }
    if (["INITIATED", "UPLOADING"].includes(current.status)) {
      if (!file) throw new Error(t("import.resume"));
      await transfer(current, file);
    }
  });
  const needsAck = state?.warnings?.includes("SINGLE_COLUMN_INPUT");
  const restart = async () => {
    if (!state) return;
    setAssetId(state.asset_id ?? ""); setName(state.asset_name ?? ""); setFormat(state.format);
    setDelimiter(state.csv_options?.delimiter ?? ","); setFile(null); setObject(null);
    setUploaded(0); setAck(false); setMapping(""); setError(null); request.current = null;
    setParams(previous => { previous.delete("import"); return previous; });
  };
  return <section className="card space-y-4" aria-label={t("assets.import")}>
    <h2>{t("assets.import")}</h2>
    {!uploadId && <>
      <Field label={t("common.search")}>{id => <input id={id} className="input" value={assetQuery} onChange={e => setAssetQuery(e.target.value)} />}</Field>
      <Field label={t("assets.existing")}>{id => <select id={id} className="input" value={assetId} onChange={e => setAssetId(e.target.value)}><option value="">{t("assets.new")}</option>{assets.data?.items.map(asset => <option key={asset.asset_id} value={asset.asset_id}>{asset.name}</option>)}</select>}</Field>
      {!assetId && <Field label={t("common.name")}>{id => <input id={id} className="input" required maxLength={255} value={name} onChange={e => setName(e.target.value)} />}</Field>}
      <div className="flex gap-2"><button className={mode === "file" ? "btn-primary" : "btn-secondary"} onClick={() => setMode("file")}>{t("import.file")}</button><button className={mode === "object" ? "btn-primary" : "btn-secondary"} onClick={() => setMode("object")}>{t("import.object")}</button></div>
      {mode === "object" && <><Field label={t("import.prefix")}>{id => <input id={id} className="input" value={prefix} onChange={e => { setPrefix(e.target.value); setToken(""); }} />}</Field><ProblemAlert error={objects.error} /><ul className="space-y-2">{objects.data?.items.map(item => <li key={item.key}><button className={object?.key === item.key ? "btn-primary" : "btn-secondary"} onClick={() => { setObject(item); if (!name) setName(item.key.split("/").pop()?.replace(/\.[^.]+$/, "") ?? ""); }}>{item.key} · {item.size_bytes}</button></li>)}</ul>{objects.data?.next_token && <button className="btn-secondary" onClick={() => setToken(objects.data!.next_token!)}>{t("common.next")}</button>}<Field label={t("common.format")}>{id => <select id={id} className="input" value={format} onChange={e => setFormat(e.target.value)}>{["CSV", "PARQUET", "JSONL"].map(f => <option key={f}>{f}</option>)}</select>}</Field></>}
      {format === "CSV" && <Field label={t("import.delimiter")}>{id => <select id={id} className="input" value={delimiter} onChange={e => setDelimiter(e.target.value)}>{[",", ";", "\t", "|"].map(d => <option key={d} value={d}>{d === "\t" ? "TAB" : d}</option>)}</select>}</Field>}
    </>}
    {(!uploadId && mode === "file" || state && ["INITIATED", "UPLOADING"].includes(state.status)) && <Field label={t("import.file")}>{id => <input id={id} className="input" type="file" accept=".csv,.parquet,.jsonl" onChange={e => selectFile(e.target.files?.[0] ?? null)} />}</Field>}
    <ProblemAlert error={error ?? session.error} onRetry={() => void session.refetch()} />
    {uploadId && <button className="btn-secondary" disabled={busy} onClick={() => void session.refetch()}>{t("operations.refresh")}</button>}
    {busy && <button className="btn-secondary" onClick={() => controller.current?.abort()}>{t("import.stop_transfer")}</button>}
    {state && (["FAILED", "REJECTED", "ABORTED"].includes(state.status) || state.error_code === "IMPORT_EXPIRED") && <ConfirmButton label={t("import.restart")} title={t("import.restart")} body={t("import.restart_help")} confirmLabel={t("components.confirm")} onConfirm={() => void restart()} disabled={busy} />}
    {(busy || state) && <div role="status" aria-live="polite"><p>{state ? t(`status.${state.status}` as TranslationKey) : t("common.loading")}</p>{mode === "file" && file && <><progress max={file.size} value={uploaded} className="w-full" /><p>{t("import.progress", { done: uploaded, total: file.size })}</p></>}</div>}
    {(!state || ["INITIATED", "UPLOADING"].includes(state.status)) && <button className="btn-primary" disabled={busy || !!uploadId && (session.isPending || session.isError) || (!state && ((!assetId && !name.trim()) || (mode === "file" ? !file : !object)))} onClick={start}>{busy ? t("common.loading") : t(state ? "import.resume_action" : "import.upload")}</button>}
    {state?.error_code && <div role="alert" className="rounded-control bg-fail-bg text-fail p-3">{t(`error.${state.error_code}` in DICTIONARY.vi ? `error.${state.error_code}` as TranslationKey : "error.generic")}<p>{state.error_code}</p></div>}
    {state && (state.status === "VERIFIED" || state.status === "REJECTED" && ["DUPLICATE_COLUMN_NAME", "EMPTY_COLUMN_NAME"].includes(state.error_code ?? "")) && <><Field label={t("import.mapping")}>{id => <input id={id} className="input" value={mapping} onChange={e => setMapping(e.target.value)} placeholder="sender_account,receiver_account" />}</Field><button className="btn-secondary" disabled={busy || !mapping.trim()} onClick={() => perform(async () => updateState(await configureImport(uploadId, mapping.split(",").map(s => s.trim()))))}>{t("import.configure")}</button></>}
    {state?.status === "VERIFIED" && <><DatasetPreview data={{ schema_definition: state.schema_definition, preview: state.preview ?? [], profile: state.profile ?? {}, warnings: state.warnings ?? [], source_descriptor: state.source_descriptor, total_rows: state.total_rows ?? 0, total_columns: state.total_columns ?? 0 } as PreviewData} />{needsAck && <label className="flex gap-2"><input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)} />{t("import.ack")}</label>}<button className="btn-primary" disabled={busy || !!needsAck && !ack} onClick={() => perform(async () => { const snap = await registerImport(uploadId, ack ? ["SINGLE_COLUMN_INPUT"] : []); updateState(await getImport(uploadId)); await client.invalidateQueries({ queryKey: ["assets"] }); setParams(previous => { previous.set("snapshot", snap.snapshot_id); return previous; }); })}>{t("import.register")}</button></>}
    {state?.status === "REGISTERED" && <div role="status" className="space-y-3"><p>{t("import.success")}</p><Link className="btn-primary" to={`/snapshots/${state.snapshot_id}`}>{t("btn.open")}</Link><Link className="btn-secondary" to={`/rulesets?snapshot=${state.snapshot_id}`}>{t("recommend.rules")}</Link><Link className="btn-secondary" to={`/policies?snapshot=${state.snapshot_id}`}>{t("recommend.policy")}</Link><Link className="btn-secondary" to={`/runs/new?snapshot=${state.snapshot_id}`}>{t("recommend.run")}</Link></div>}
    {state && ["INITIATED", "UPLOADING", "STAGED", "VERIFIED"].includes(state.status) && <button className="btn-secondary" disabled={busy} onClick={() => perform(async () => { controller.current?.abort(); updateState(await abortImport(uploadId)); })}>{t("import.abort")}</button>}
  </section>;
}
