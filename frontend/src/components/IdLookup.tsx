import { ArrowRight } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { useI18n } from "../lib/i18n";
import { Field } from "./Field";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const isUuid = (value: string) => UUID_PATTERN.test(value.trim());

/** Open a record by ID: the explicit substitute for browse lists until list APIs exist. */
export function IdLookup({ label, to, button }: { label: string; to: (id: string) => string; button?: string }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [value, setValue] = useState("");
  const valid = isUuid(value);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (valid) navigate(to(value.trim()));
  };

  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
      <div className="flex-1 min-w-64">
        <Field label={label}>
          {(id) => (
            <input
              id={id}
              className="input mono"
              placeholder="00000000-0000-0000-0000-000000000000"
              value={value}
              spellCheck={false}
              aria-invalid={value !== "" && !valid}
              onChange={(e) => setValue(e.target.value)}
            />
          )}
        </Field>
      </div>
      <button type="submit" className="btn-secondary" disabled={!valid}>
        {button ?? t("btn.open")} <ArrowRight aria-hidden className="size-4" />
      </button>
    </form>
  );
}
