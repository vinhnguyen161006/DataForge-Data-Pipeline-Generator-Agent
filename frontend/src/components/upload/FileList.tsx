import type { ReactNode } from "react";
import { formatBytes } from "../../format";
import type { FileEntry } from "../../hooks/useBatchUpload";
import { describeError } from "../workspace/LoadError";

type Tone = "muted" | "run" | "warn" | "ok" | "bad";

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

function statusLine(entry: FileEntry): { tone: Tone; text: ReactNode } {
  const columns = entry.source ? plural(entry.source.columns.length, "column") : "";
  const warnings = entry.source?.warnings.length ?? 0;
  const detail = (
    <>
      {" "}
      &middot; {columns}
      {warnings > 0 && <> &middot; {plural(warnings, "warning")}</>}
    </>
  );
  switch (entry.status) {
    case "uploading":
      return { tone: "run", text: "Uploading and detecting the format..." };
    case "confirming":
      return { tone: "run", text: "Saving the read configuration..." };
    case "failed":
      return { tone: "bad", text: describeError(entry.error) };
    case "confirmed":
      return { tone: "ok", text: <>Confirmed{detail}</> };
    case "review":
      return { tone: warnings > 0 ? "warn" : "muted", text: <>Read config needs review{detail}</> };
  }
}

export function FileList({
  entries,
  selectedKey,
  onSelect,
  onRetry,
  onRemove,
  canRemove = true,
}: {
  entries: FileEntry[];
  selectedKey: string | null;
  onSelect: (key: string) => void;
  onRetry: (key: string) => void;
  onRemove: (key: string) => void;
  canRemove?: boolean;
}) {
  if (entries.length === 0) {
    return null;
  }
  return (
    <ul aria-label="Batch files" className="up-files">
      {entries.map((entry) => {
        const line = statusLine(entry);
        const failed = entry.status === "failed";
        return (
          <li key={entry.key} className={entry.key === selectedKey ? "selected" : undefined}>
            <button
              type="button"
              className="up-file"
              aria-pressed={entry.key === selectedKey}
              disabled={entry.source === null}
              onClick={() => onSelect(entry.key)}
            >
              <span className="lp-mono up-file-name">{entry.name}</span>
              <span className={`up-file-status ${line.tone}`}>{line.text}</span>
            </button>
            <span className="up-file-size">{formatBytes(entry.size)}</span>
            {failed ? (
              <span className="up-file-actions">
                <button type="button" className="ws-link" onClick={() => onRetry(entry.key)}>
                  Retry
                </button>
                {canRemove && (
                  <button
                    type="button"
                    className="up-remove"
                    aria-label={`Remove ${entry.name}`}
                    onClick={() => onRemove(entry.key)}
                  >
                    &times;
                  </button>
                )}
              </span>
            ) : (
              <span />
            )}
          </li>
        );
      })}
    </ul>
  );
}
