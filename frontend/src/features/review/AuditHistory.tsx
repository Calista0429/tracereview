import { FIELD_LABELS, type AuditEvent, type FieldKey } from "../../domain/types";
import { formatUtc } from "../../lib/format";

function label(key: unknown): string {
  return typeof key === "string" && key in FIELD_LABELS ? FIELD_LABELS[key as FieldKey] : String(key);
}

function show(value: unknown): string {
  return value === null || value === undefined || value === "" ? "empty" : String(value);
}

interface Change {
  key: string;
  before: unknown;
  after: unknown;
}

export function describeEvent(event: AuditEvent): { summary: string; changes: Change[]; reason: string | null } {
  const p = event.payload;
  switch (event.event_type) {
    case "IMPORTED":
      return { summary: `Imported ${show(p.filename)}`, changes: [], reason: null };
    case "FIELDS_UPDATED":
      return {
        summary: "Saved field changes",
        changes: Array.isArray(p.changes) ? (p.changes as Change[]) : [],
        reason: typeof p.reason === "string" ? p.reason : null,
      };
    case "FIELD_VERIFICATION_CHANGED":
      return {
        summary: `${p.verified ? "Checked" : "Unchecked"} ${label(p.field_key)} against the PDF`,
        changes: [],
        reason: null,
      };
    case "CONFIRMED":
      return { summary: "Confirmed the review", changes: [], reason: null };
    case "CONFIRMATION_REVOKED":
      return { summary: "Confirmation revoked because fields changed", changes: [], reason: null };
    case "EXPORT_GENERATED":
      return { summary: `Generated a JSON export of version ${show(p.exported_version)}`, changes: [], reason: null };
  }
}

export function AuditHistory({ events }: { events: AuditEvent[] }) {
  return (
    <details className="history">
      <summary>History ({events.length})</summary>
      <ol className="history__list">
        {events.map((event) => {
          const { summary, changes, reason } = describeEvent(event);
          return (
            <li key={event.id}>
              <p className="history__line">
                <strong>{summary}</strong>
                <span className="history__meta">
                  {event.actor}, version {event.document_version}, {formatUtc(event.created_at)}
                </span>
              </p>
              {changes.length > 0 && (
                <ul className="history__changes">
                  {changes.map((c) => (
                    <li key={c.key}>
                      {label(c.key)}: <span className="num">{show(c.before)}</span> to{" "}
                      <span className="num">{show(c.after)}</span>
                    </li>
                  ))}
                </ul>
              )}
              {reason && <p className="history__reason">Reason: {reason}</p>}
            </li>
          );
        })}
      </ol>
    </details>
  );
}
