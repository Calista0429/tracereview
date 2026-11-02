import type { RuleResult } from "../../domain/types";
import { RULE_GLYPH, RULE_NAMES, RULE_STATUS_TEXT } from "../../lib/format";

interface Props {
  rules: RuleResult[];
  /** True while the page holds edits the rules have not seen yet. */
  describesSavedVersion: boolean;
}

export function ValidationResults({ rules, describesSavedVersion }: Props) {
  return (
    <section className="rules" aria-labelledby="rules-heading">
      <h2 id="rules-heading">Rule checks</h2>
      {describesSavedVersion && (
        <p className="note">Rules describe the saved version of this document.</p>
      )}
      <ul className="rules__list">
        {rules.map((rule) => (
          <li key={rule.id} className={`rule rule--${rule.status.toLowerCase()}`}>
            <span className="rule__glyph" aria-hidden="true">
              {RULE_GLYPH[rule.status]}
            </span>
            <div>
              <p className="rule__title">
                <span className="rule__name">{RULE_NAMES[rule.id]}</span>
                <span className="rule__status">{RULE_STATUS_TEXT[rule.status]}</span>
              </p>
              <p className="rule__message">{rule.message}</p>
            </div>
          </li>
        ))}
      </ul>
      <p className="note">
        Passing rules means no problem was found. It does not replace checking each value against the PDF.
      </p>
    </section>
  );
}
