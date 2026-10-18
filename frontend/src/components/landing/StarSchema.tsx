const DIMENSIONS = [
  { name: "dim_customer", x: 20, y: 20 },
  { name: "dim_product", x: 360, y: 20 },
  { name: "dim_date", x: 190, y: 232 },
];

export function StarSchema({ variant }: { variant: "hero" | "tile" }) {
  const hero = variant === "hero";
  return (
    <svg className="lp-schema" viewBox="0 0 520 300" aria-hidden="true">
      <g stroke="#958D84" strokeWidth={hero ? 1.2 : 1.5}>
        <line x1="185" y1="135" x2="160" y2="62" />
        <line x1="335" y1="135" x2="360" y2="62" />
        <line x1="260" y1="185" x2="260" y2="232" />
      </g>
      <rect x="185" y="115" width="150" height="70" fill="#111111" />
      <text
        x="260"
        y={hero ? 146 : 156}
        fill="#FFFFFF"
        fontFamily="JetBrains Mono"
        fontSize={hero ? 13 : 15}
        textAnchor="middle"
      >
        fct_order_lines
      </text>
      {hero && (
        <text x="260" y="166" fill="#B7B1AA" fontFamily="Inter" fontSize="11" textAnchor="middle">
          grain &middot; order line
        </text>
      )}
      {DIMENSIONS.map((dimension) => (
        <g key={dimension.name}>
          <rect
            x={dimension.x}
            y={dimension.y}
            width="140"
            height="56"
            fill={hero ? "#F6F0E8" : "#FFFFFF"}
            stroke="#D9CEC1"
          />
          <text
            x={dimension.x + 70}
            y={dimension.y + 33}
            fill="#111111"
            fontFamily="JetBrains Mono"
            fontSize={hero ? 12 : 14}
            textAnchor="middle"
          >
            {dimension.name}
          </text>
        </g>
      ))}
    </svg>
  );
}
