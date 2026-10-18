import type { CsvReadConfig } from "../../api/types";
import type { FileEntry } from "../../hooks/useBatchUpload";
import { describeError } from "../workspace/LoadError";

type Choice = [value: string, label: string];

const ENCODINGS: Choice[] = [
  ["utf-8", "UTF-8"],
  ["utf-8-sig", "UTF-8 with BOM"],
  ["latin-1", "Latin-1"],
  ["utf-16", "UTF-16"],
];

const DELIMITERS: Choice[] = [
  [",", "Comma ( , )"],
  [";", "Semicolon ( ; )"],
  ["\t", "Tab"],
  ["|", "Pipe ( | )"],
];

const NULL_PRESETS: string[][] = [["", "NULL"], ["NA", "N/A"], ["\\N"]];

const DATE_FORMATS: Choice[] = [
  ["", "Auto-detect"],
  ["%Y-%m-%d", "YYYY-MM-DD"],
  ["%d/%m/%Y", "DD/MM/YYYY"],
  ["%m/%d/%Y", "MM/DD/YYYY"],
];

const TIMESTAMP_FORMATS: Choice[] = [
  ["", "Auto-detect"],
  ["%Y-%m-%d %H:%M:%S", "YYYY-MM-DD HH:mm:ss"],
  ["%d/%m/%Y %H:%M:%S", "DD/MM/YYYY HH:mm:ss"],
];

function withCurrent(choices: Choice[], current: string): Choice[] {
  return choices.some(([value]) => value === current)
    ? choices
    : [...choices, [current, `Detected: ${current}`]];
}

function tokensKey(tokens: string[]): string {
  return JSON.stringify([...tokens].sort());
}

function tokensLabel(tokens: string[]): string {
  return tokens.map((token) => (token === "" ? "empty" : token)).join(", ") || "none";
}

function nullChoices(current: string[]): Choice[] {
  const presets = NULL_PRESETS.map((tokens): Choice => [tokensKey(tokens), tokensLabel(tokens)]);
  const key = tokensKey(current);
  return presets.some(([value]) => value === key)
    ? presets
    : [...presets, [key, `Detected: ${tokensLabel(current)}`]];
}

function SelectField({
  label,
  value,
  choices,
  onChange,
}: {
  label: string;
  value: string;
  choices: Choice[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="up-select">
      {label}
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {choices.map(([choice, text]) => (
          <option key={choice} value={choice}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
}

export function ReadConfigPanel({
  entry,
  onChange,
  onConfirm,
}: {
  entry: FileEntry | null;
  onChange: (draft: CsvReadConfig) => void;
  onConfirm: () => void;
}) {
  if (!entry?.draft) {
    return <p className="ws-muted">Add a CSV file to review how it is read.</p>;
  }
  const config = entry.draft;
  const busy = entry.status === "confirming";
  const set = <K extends keyof CsvReadConfig>(key: K, value: CsvReadConfig[K]) =>
    onChange({ ...config, [key]: value });

  return (
    <fieldset className="up-config" disabled={busy}>
      <legend>
        Read configuration &middot; <span className="lp-mono up-config-file">{entry.name}</span>
      </legend>
      <div className="up-config-grid">
        <SelectField
          label="Encoding"
          value={config.encoding}
          choices={withCurrent(ENCODINGS, config.encoding)}
          onChange={(value) => set("encoding", value)}
        />
        <SelectField
          label="Delimiter"
          value={config.delimiter}
          choices={withCurrent(DELIMITERS, config.delimiter)}
          onChange={(value) => set("delimiter", value)}
        />
        <SelectField
          label="Null values"
          value={tokensKey(config.null_tokens)}
          choices={nullChoices(config.null_tokens)}
          onChange={(value) => set("null_tokens", JSON.parse(value) as string[])}
        />
        <SelectField
          label="Date format"
          value={config.date_format ?? ""}
          choices={withCurrent(DATE_FORMATS, config.date_format ?? "")}
          onChange={(value) => set("date_format", value || null)}
        />
      </div>
      <details className="up-more">
        <summary>More options</summary>
        <div className="up-config-grid">
          <SelectField
            label="Timestamp format"
            value={config.timestamp_format ?? ""}
            choices={withCurrent(TIMESTAMP_FORMATS, config.timestamp_format ?? "")}
            onChange={(value) => set("timestamp_format", value || null)}
          />
          <label className="up-select">
            Skip rows
            <input
              type="number"
              min={0}
              value={config.skip_rows}
              onChange={(event) => set("skip_rows", Math.max(0, Number(event.target.value)))}
            />
          </label>
          <label className="up-select">
            Quote
            <input
              className="lp-mono"
              maxLength={1}
              value={config.quote}
              onChange={(event) => set("quote", event.target.value)}
            />
          </label>
          <label className="up-select">
            Escape
            <input
              className="lp-mono"
              maxLength={1}
              value={config.escape}
              onChange={(event) => set("escape", event.target.value)}
            />
          </label>
        </div>
        <label className="up-check">
          <input
            type="checkbox"
            checked={config.has_header}
            onChange={(event) => set("has_header", event.target.checked)}
          />
          <span>First row is a header</span>
        </label>
      </details>
      {entry.status === "review" && entry.error !== null && (
        <p className="up-error" role="alert">
          {describeError(entry.error)}
        </p>
      )}
      <div className="up-config-actions">
        {entry.status === "confirmed" ? (
          <span className="up-confirmed">Read configuration confirmed</span>
        ) : (
          <button type="button" className="lp-button small" disabled={busy} onClick={onConfirm}>
            {busy ? "Saving..." : "Confirm read configuration"}
          </button>
        )}
      </div>
    </fieldset>
  );
}
