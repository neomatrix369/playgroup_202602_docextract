/**
 * Doc Risk Auditor — extraction summary + risk flags + one-click decision UI.
 * Plain React; styles in DocRiskResultsPanel.css (no UI libraries).
 */

import "./DocRiskResultsPanel.css";

export type RiskSeverity = "low" | "medium" | "high";

export interface RiskFlag {
  id: string;
  label: string;
  severity: RiskSeverity;
}

export interface ExtractedFields {
  charity_number?: string;
  charity_name?: string;
  report_date?: string;
  income_annually_in_british_pounds?: string;
  spending_annually_in_british_pounds?: string;
  address__postcode?: string;
  address__post_town?: string;
  address__street_line?: string;
}

export type ReviewDecision = "approve" | "review" | "reject";

export interface DocRiskResultsPanelProps {
  filename: string;
  /** Optional F1 / confidence from your scorer for demo trust line */
  extractionScoreLabel?: string;
  fields: ExtractedFields;
  flags: RiskFlag[];
  onDecision?: (d: ReviewDecision) => void;
}

function inferDecision(flags: RiskFlag[]): ReviewDecision {
  if (flags.some((f) => f.severity === "high")) return "reject";
  if (flags.some((f) => f.severity === "medium")) return "review";
  return "approve";
}

export function DocRiskResultsPanel({
  filename,
  extractionScoreLabel,
  fields,
  flags,
  onDecision,
}: DocRiskResultsPanelProps) {
  const suggested = inferDecision(flags);

  const entries: [string, string | undefined][] = [
    ["Charity number", fields.charity_number],
    ["Charity name", fields.charity_name],
    ["Report date", fields.report_date],
    ["Income (£)", fields.income_annually_in_british_pounds],
    ["Spending (£)", fields.spending_annually_in_british_pounds],
    ["Postcode", fields.address__postcode],
    ["Town", fields.address__post_town],
    ["Street", fields.address__street_line],
  ];

  return (
    <article className="doc-risk-panel" aria-label="Document risk review">
      <h2>Extraction &amp; risk review</h2>
      <p className="doc-risk-panel__meta">
        File: {filename}
        {extractionScoreLabel ? ` · ${extractionScoreLabel}` : ""}
        <br />
        Suggested: <strong>{suggested}</strong>
      </p>

      <div className="doc-risk-panel__section-title">Structured fields</div>
      <dl className="doc-risk-grid">
        {entries.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v ?? "—"}</dd>
          </div>
        ))}
      </dl>

      <div className="doc-risk-panel__section-title">Risk flags</div>
      {flags.length === 0 ? (
        <p className="doc-risk-panel__meta">No flags.</p>
      ) : (
        <ul className="doc-risk-flags">
          {flags.map((f) => (
            <li key={f.id} data-severity={f.severity}>
              <strong>[{f.severity}]</strong> {f.label}
            </li>
          ))}
        </ul>
      )}

      <div className="doc-risk-decision">
        <button type="button" data-action="approve" onClick={() => onDecision?.("approve")}>
          Approve
        </button>
        <button type="button" data-action="review" onClick={() => onDecision?.("review")}>
          Needs review
        </button>
        <button type="button" data-action="reject" onClick={() => onDecision?.("reject")}>
          Reject
        </button>
      </div>
    </article>
  );
}
