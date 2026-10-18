import { Fragment, useState } from "react";
import type { DataDesign } from "../../api/types";
import { decisionsOf, entitiesOf } from "./designView";
import { SchemaDiagram } from "./SchemaDiagram";

export function EntityPanel({ design }: { design: DataDesign }) {
  const entities = entitiesOf(design);
  const [selected, setSelected] = useState(entities[0]?.name ?? "");
  const entity = entities.find((candidate) => candidate.name === selected) ?? entities[0];
  const factName = entity?.kind === "fact" ? entity.name : design.facts[0].name;

  return (
    <div className="gt-entity">
      <div className="gt-diagram-frame">
        <SchemaDiagram design={design} factName={factName} />
      </div>
      <div role="tablist" aria-label="Entities" className="gt-tabs">
        {entities.map((candidate) => (
          <button
            key={candidate.name}
            type="button"
            role="tab"
            aria-selected={candidate.name === entity?.name}
            className="gt-tab"
            onClick={() => setSelected(candidate.name)}
          >
            {candidate.name}
          </button>
        ))}
      </div>
      {entity && (
        <div role="tabpanel">
          <div className="gt-entity-summary">{entity.summary}</div>
          {entity.fields.length === 0 ? (
            <p className="ws-muted">No fields listed.</p>
          ) : (
            entity.fields.map((field) => (
              <div key={`${field.role}-${field.name}`} className="gt-field-row">
                <span className="lp-mono">{field.name}</span>
                <span className="lp-mono gt-faint">{field.role}</span>
                <span className="gt-faint">{field.note}</span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

export function DecisionList({ design }: { design: DataDesign }) {
  return (
    <ol className="gt-decisions">
      {decisionsOf(design).map((decision) => {
        const confirmed = decision.open.length === 0;
        return (
          <li key={decision.index} id={`decision-${decision.index}`}>
            <span className="gt-decision-index">{decision.index}</span>
            <div>
              <div className="gt-decision-head">
                <span className="gt-decision-topic">{decision.topic}</span>
                <span className={confirmed ? "gt-state ok" : "gt-state warn"}>
                  {confirmed ? "Confirmed" : "Needs input"}
                </span>
              </div>
              <div className="gt-decision-value">
                {decision.lines.map((line, at) => (
                  <Fragment key={`${decision.index}-line-${at.toString()}`}>
                    {at > 0 && <br />}
                    {line}
                  </Fragment>
                ))}
              </div>
              {decision.why.length > 0 && (
                <div className="gt-decision-why">{decision.why.join(" ")}</div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export function ConstraintList({ design }: { design: DataDesign }) {
  return (
    <div className="gt-block">
      <h2 className="ws-h2">Constraints that become required tests</h2>
      <p className="gt-hint">
        An observation is not a rule. Only these approved constraints become required tests in the
        generated project.
      </p>
      {design.constraints.length === 0 ? (
        <p className="ws-muted">No constraints proposed.</p>
      ) : (
        design.constraints.map((constraint) => (
          <div
            key={`${constraint.layer}-${constraint.model}-${constraint.kind}-${constraint.columns.join(",")}`}
            className="gt-constraint"
          >
            <span>
              <span className="lp-mono">
                {constraint.layer}.{constraint.model}
              </span>{" "}
              &middot; {constraint.kind.replaceAll("_", " ")} &middot;{" "}
              <span className="lp-mono">{constraint.columns.join(", ")}</span>
            </span>
            {constraint.evidence && <span className="gt-faint">{constraint.evidence}</span>}
          </div>
        ))
      )}
      {design.assumptions.length > 0 && (
        <>
          <h2 className="ws-h2 gt-assumptions">Assumptions</h2>
          <ul className="gt-assumption-list">
            {design.assumptions.map((assumption) => (
              <li key={assumption}>{assumption}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
