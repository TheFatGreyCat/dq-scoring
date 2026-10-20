import { formatTimestamp } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type { AdapterObservation } from "./operationsApi";
import { useOperationsText, type OperationsTextKey } from "./operationsText";

export function AdapterPanel({ adapters }: { adapters: AdapterObservation[] }) {
  const { lang } = useI18n();
  const text = useOperationsText();
  const when = (value: string | null) => (value ? formatTimestamp(value, lang).local : text("never"));
  return (
    <section className="card overflow-x-auto" aria-labelledby="adapters-title">
      <h2 id="adapters-title">{text("adapters")}</h2>
      <table className="w-full">
        <tbody>
          {adapters.map(adapter => (
            <tr key={adapter.name} className="align-top">
              <th scope="row" className="text-left p-2">{text(`adapter_${adapter.name}` as OperationsTextKey)}</th>
              <td className="p-2 font-semibold">{text(`state_${adapter.state}` as OperationsTextKey)}{adapter.stale && ` · ${text("stale")}`}</td>
              <td className="p-2">{text(`source_${adapter.source}` as OperationsTextKey)}</td>
              <td className="p-2">{text("checked")}: {when(adapter.checked_at)}</td>
              <td className="p-2">{text("last_success")}: {when(adapter.last_success_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
