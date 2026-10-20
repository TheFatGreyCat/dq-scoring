import { useState } from "react";
import type { DatasetPreview as PreviewData } from "../../api/types";
import { Field } from "../../components/Field";
import { useI18n } from "../../lib/i18n";

/** `hideSourceInfo`: omit the row/column counts and hash/size block when the host already shows them. */
export function DatasetPreview({ data, hideSourceInfo = false }: { data: PreviewData; hideSourceInfo?: boolean }) {
  const { t } = useI18n();
  const [search, setSearch] = useState("");
  const [columnSearch, setColumnSearch] = useState("");
  const schema = (data.schema_definition.columns ?? []) as ({ name: string; original_name?: string; type?: string } | string)[];
  const columns = schema.map(c => typeof c === "string" ? c : c.name).filter(name => name.toLowerCase().includes(columnSearch.toLowerCase()));
  const shown = data.preview.length;
  const needle = search.toLowerCase();
  const rows = data.preview.filter(row => Object.values(row).some(value => String(value ?? "").toLowerCase().includes(needle)));
  return <section className="space-y-4 min-w-0" aria-label={t("preview.title")}>
    <h2>{t("preview.title")}</h2>
    {!hideSourceInfo && <p>{t("preview.rows", { count: data.total_rows })} · {t("preview.columns", { count: data.total_columns })}</p>}
    <p className="text-sm text-fg-muted" role="status">
      {t("preview.showing", { shown, total: data.total_rows })}
      {search && ` · ${t("preview.matches", { count: rows.length, shown })}`}
    </p>
    <p className="text-sm text-fg-muted">{t("preview.sample")}</p>
    <div className="grid gap-3 sm:grid-cols-2">
      <Field label={t("common.search")}>{id => <input id={id} type="search" className="input" value={search} onChange={e => setSearch(e.target.value)} />}</Field>
      <Field label={t("preview.column_search")}>{id => <input id={id} type="search" className="input" value={columnSearch} onChange={e => setColumnSearch(e.target.value)} />}</Field>
    </div>
    {columns.length === 0 ? <p className="text-sm text-fg-muted italic">{t("preview.no_columns")}</p>
      : shown === 0 ? <p className="text-sm text-fg-muted italic">{t("preview.no_rows")}</p>
      : rows.length === 0 ? <p className="text-sm text-fg-muted italic">{t("preview.no_match")}</p>
      : <div className="overflow-auto max-h-[28rem] max-w-full rounded border border-border"><table className="w-full text-sm"><thead className="sticky top-0 bg-surface"><tr>{columns.map(name => <th className="p-2 text-left whitespace-nowrap" key={name}>{name}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <tr key={index}>{columns.map(name => <td className="p-2 border-t border-border whitespace-nowrap" key={name}>{row[name] == null ? <em className="text-fg-muted">{t("preview.null")}</em> : row[name] === "" ? <em>{t("preview.empty")}</em> : String(row[name])}</td>)}</tr>)}</tbody></table></div>}
    <details><summary>{t("preview.schema")}</summary><ul>{schema.map((c, i) => <li key={i}>{typeof c === "string" ? c : `${c.original_name ?? c.name} → ${c.name} (${c.type ?? "STRING"})`}</li>)}</ul></details>
    {!hideSourceInfo && <dl className="text-sm break-all"><dt>{t("preview.hash")}</dt><dd className="mono">{String(data.source_descriptor.content_sha256 ?? "—")}</dd><dt>{t("preview.size")}</dt><dd>{String(data.source_descriptor.size_bytes ?? "—")}</dd></dl>}
  </section>;
}
