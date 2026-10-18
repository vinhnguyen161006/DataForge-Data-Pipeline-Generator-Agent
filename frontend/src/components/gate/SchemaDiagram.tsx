import type { DataDesign } from "../../api/types";

const FACT = { x: 185, y: 115, width: 150, height: 70 };
const DIMENSION = { width: 140, height: 56 };
const SLOTS = [
  { x: 20, y: 20 },
  { x: 360, y: 20 },
  { x: 190, y: 232 },
  { x: 20, y: 232 },
  { x: 360, y: 232 },
];

function shorten(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 3)}...` : text;
}

export function SchemaDiagram({ design, factName }: { design: DataDesign; factName: string }) {
  const fact = design.facts.find((candidate) => candidate.name === factName) ?? design.facts[0];
  const shown = design.dimensions.slice(0, SLOTS.length);
  const hidden = design.dimensions.length - shown.length;
  const center = { x: FACT.x + FACT.width / 2, y: FACT.y + FACT.height / 2 };
  const label = `Star schema: ${fact.name} joined to ${
    shown.map((dimension) => dimension.name).join(", ") || "no dimensions"
  }`;

  return (
    <svg viewBox="0 0 520 300" className="gt-diagram" role="img" aria-label={label}>
      <g stroke="#958D84" strokeWidth="1.3">
        {shown.map((dimension, index) => (
          <line
            key={dimension.name}
            x1={center.x}
            y1={center.y}
            x2={SLOTS[index].x + DIMENSION.width / 2}
            y2={SLOTS[index].y + DIMENSION.height / 2}
          />
        ))}
      </g>
      <rect x={FACT.x} y={FACT.y} width={FACT.width} height={FACT.height} fill="#111111" />
      <text
        x={center.x}
        y={146}
        fill="#FFFFFF"
        fontFamily="JetBrains Mono"
        fontSize="13"
        textAnchor="middle"
      >
        {shorten(fact.name, 20)}
      </text>
      <text
        x={center.x}
        y={166}
        fill="#B7B1AA"
        fontFamily="Inter"
        fontSize="11"
        textAnchor="middle"
      >
        fact &middot; {fact.measures.length} measure{fact.measures.length === 1 ? "" : "s"}
      </text>
      {shown.map((dimension, index) => {
        const slot = SLOTS[index];
        return (
          <g key={dimension.name}>
            <rect
              x={slot.x}
              y={slot.y}
              width={DIMENSION.width}
              height={DIMENSION.height}
              fill="#FFFFFF"
              stroke="#D9CEC1"
            />
            <text
              x={slot.x + DIMENSION.width / 2}
              y={slot.y + 25}
              fill="#111111"
              fontFamily="JetBrains Mono"
              fontSize="12"
              textAnchor="middle"
            >
              {shorten(dimension.name, 18)}
            </text>
            <text
              x={slot.x + DIMENSION.width / 2}
              y={slot.y + 43}
              fill="#958D84"
              fontFamily="Inter"
              fontSize="10.5"
              textAnchor="middle"
            >
              {shorten(`key: ${dimension.business_key.join(", ")}`, 24)}
            </text>
          </g>
        );
      })}
      {hidden > 0 && (
        <text x="510" y="295" fill="#77716B" fontFamily="Inter" fontSize="11" textAnchor="end">
          +{hidden} more dimension{hidden === 1 ? "" : "s"}
        </text>
      )}
    </svg>
  );
}
