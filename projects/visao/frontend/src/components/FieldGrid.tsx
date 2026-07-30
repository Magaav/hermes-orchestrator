import type { FormField } from "../form/types";

type Props = {
  fields: FormField[];
  values: Record<string, string>;
  invalid: Set<string>;
  onChange: (key: string, value: string) => void;
};

export function FieldGrid({ fields, values, invalid, onChange }: Props) {
  return (
    <div className="field-grid">
      {fields.map((field) => {
        const id = `field-${field.key.replaceAll(".", "-")}`;
        const classes = `${field.wide ? "field--wide" : ""} ${invalid.has(field.key) ? "field--invalid" : ""}`;
        return (
          <label className={classes} key={field.key} htmlFor={id}>
            <span>{field.label}{field.required && <b aria-label="obrigatório">*</b>}</span>
            {field.type === "select" ? (
              <select id={id} value={values[field.key] || ""} onChange={(event) => onChange(field.key, event.target.value)} aria-invalid={invalid.has(field.key)}>
                {field.options?.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}
              </select>
            ) : field.type === "textarea" ? (
              <textarea id={id} value={values[field.key] || ""} placeholder={field.placeholder} onChange={(event) => onChange(field.key, event.target.value)} rows={5} aria-invalid={invalid.has(field.key)} />
            ) : (
              <input
                id={id}
                type={field.type === "email" || field.type === "date" || field.type === "number" ? field.type : "text"}
                inputMode={field.type === "currency" ? "decimal" : field.type === "tel" ? "tel" : undefined}
                value={values[field.key] || ""}
                placeholder={field.type === "currency" ? "R$ 0,00" : field.placeholder}
                onChange={(event) => onChange(field.key, event.target.value)}
                aria-invalid={invalid.has(field.key)}
              />
            )}
            {field.help && <small>{field.help}</small>}
            {invalid.has(field.key) && <small className="field-error">Campo obrigatório</small>}
          </label>
        );
      })}
    </div>
  );
}
