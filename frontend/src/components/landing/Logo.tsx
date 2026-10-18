export function Logo({ width = 22 }: { width?: number }) {
  return (
    <svg width={width} height={(width * 20) / 22} viewBox="0 0 22 20" aria-hidden="true">
      <rect x="0" y="0" width="22" height="5" fill="#111111" />
      <rect x="3" y="7.5" width="16" height="5" fill="#77716B" />
      <rect x="6" y="15" width="10" height="5" fill="#E6D1BB" />
    </svg>
  );
}
