import {
  AMOUNT_KEYS,
  FIELD_LABELS,
  type FieldKey,
  type FieldRecord,
} from "../../domain/types";
import type { Drafts } from "../../domain/fieldInput";

interface Props {
  fields: FieldRecord[];
  drafts: Drafts;
  /** Format errors computed from the draft, plus any the server returned. */
  errors: Partial<Record<FieldKey, string>>;
  selectedKey: FieldKey | null;
  /** Inputs are locked (confirmed record, or a request is in flight). */
  inputsDisabled: boolean;
  /** The "checked against PDF" boxes are locked. */
  checksDisabled: boolean;
  onSelect: (key: FieldKey) => void;
  onChange: (key: FieldKey, text: string) => void;
  onToggleChecked: (key: FieldKey, checked: boolean) => void;
}

export function FieldEditor(props: Props) {
  const { fields, drafts, errors, selectedKey, inputsDisabled, checksDisabled } = props;
  return (
    <section className="fields" aria-labelledby="fields-heading">
      <h2 id="fields-heading">Fields</h2>
      <ul className="fields__list">
        {fields.map((field) => {
          const key = field.key;
          const label = FIELD_LABELS[key];
          const isAmount = AMOUNT_KEYS.includes(key);
          const value = drafts[key] ?? field.current_value ?? "";
          const error = errors[key];
          const noLocation = field.evidence === null;
          const canCheck = !checksDisabled && !noLocation && field.current_value !== null;
          return (
            <li
              key={key}
              data-testid={`field-${key}`}
              className={`field${selectedKey === key ? " field--selected" : ""}`}
              onClick={() => props.onSelect(key)}
            >
              <div className="field__entry">
                <label htmlFor={`input-${key}`} className="field__label">
                  {label}
                </label>
                <div className="field__control">
                  {isAmount && (
                    <span className="field__unit" aria-hidden="true">
                      USD
                    </span>
                  )}
                  <input
                    id={`input-${key}`}
                    type="text"
                    className={`field__input${isAmount ? " num" : ""}`}
                    value={value}
                    inputMode={isAmount ? "decimal" : key === "due_date" ? "numeric" : "text"}
                    autoComplete="off"
                    spellCheck={false}
                    disabled={inputsDisabled}
                    aria-invalid={error ? true : undefined}
                    aria-describedby={error ? `error-${key}` : undefined}
                    placeholder={key === "due_date" ? "YYYY-MM-DD" : undefined}
                    onFocus={() => props.onSelect(key)}
                    onChange={(event) => props.onChange(key, event.target.value)}
                  />
                </div>
                {error && (
                  <p id={`error-${key}`} className="field__error">
                    {error}
                  </p>
                )}
              </div>

              <dl className="field__trace">
                <div>
                  <dt>Extracted</dt>
                  <dd className="num">{field.initial_extracted_value ?? <em>Nothing extracted</em>}</dd>
                </div>
                <div>
                  <dt>PDF text</dt>
                  <dd className="num">{field.source_text ?? <em>Not found in the PDF</em>}</dd>
                </div>
              </dl>

              <div className="field__state">
                {field.modified && <span className="tag">Edited</span>}
                {noLocation && <span className="tag tag--warn">No source location</span>}
                <label className="check">
                  <input
                    id={`check-${key}`}
                    type="checkbox"
                    checked={field.verified}
                    disabled={!canCheck}
                    onFocus={() => props.onSelect(key)}
                    onChange={(event) => props.onToggleChecked(key, event.target.checked)}
                  />
                  <span>
                    Checked against PDF<span className="sr-only">: {label}</span>
                  </span>
                </label>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
