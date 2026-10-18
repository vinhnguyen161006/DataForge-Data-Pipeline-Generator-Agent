const BYTE_UNITS = ["B", "KB", "MB", "GB"];
const BYTES_PER_UNIT = 1024;
const ONE_DECIMAL_BELOW = 10;

export function formatBytes(bytes: number): string {
  let value = bytes;
  let unit = 0;
  while (value >= BYTES_PER_UNIT && unit < BYTE_UNITS.length - 1) {
    value /= BYTES_PER_UNIT;
    unit += 1;
  }
  const digits = unit === 0 || value >= ONE_DECIMAL_BELOW ? 0 : 1;
  return `${value.toFixed(digits)} ${BYTE_UNITS[unit]}`;
}
