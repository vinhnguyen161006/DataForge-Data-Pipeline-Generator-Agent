import type { SourceFile } from "../../api/types";

interface PreviewRow {
  id: string;
  cells: { column: string; value: string | null }[];
}

function toRows(source: SourceFile): PreviewRow[] {
  return source.preview.map((row, position) => ({
    id: `row-${position}`,
    cells: source.columns.map((column, at) => ({ column, value: row[at] ?? null })),
  }));
}

function Warnings({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) {
    return <span className="up-preview-ok">No parsing warnings</span>;
  }
  if (warnings.length === 1) {
    return <span className="up-preview-warn">1 parsing warning: {warnings[0]}</span>;
  }
  return (
    <details className="up-preview-warn">
      <summary className="up-warn-toggle">{warnings.length} parsing warnings</summary>
      <ul>
        {warnings.map((warning) => (
          <li key={warning}>{warning}</li>
        ))}
      </ul>
    </details>
  );
}

export function PreviewTable({ source }: { source: SourceFile }) {
  return (
    <div>
      <div className="up-preview-head">
        <h2 className="ws-h2">
          Preview &middot; <span className="lp-mono up-preview-file">{source.filename}</span>
        </h2>
        <Warnings warnings={source.warnings} />
      </div>
      {source.preview.length === 0 ? (
        <p className="ws-muted">The file has no data rows to preview.</p>
      ) : (
        <div className="up-preview">
          <table>
            <thead>
              <tr>
                {source.columns.map((column) => (
                  <th key={column} scope="col">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {toRows(source).map((row) => (
                <tr key={row.id}>
                  {row.cells.map((cell) => (
                    <td key={cell.column}>
                      {cell.value === null ? (
                        <span className="up-null" title="null">
                          &empty;
                        </span>
                      ) : (
                        cell.value
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
