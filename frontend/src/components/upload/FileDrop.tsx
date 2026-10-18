import { type DragEvent, useState } from "react";

function csvFiles(list: FileList | null): File[] {
  return Array.from(list ?? []).filter(
    (file) => file.name.toLowerCase().endsWith(".csv") || file.type === "text/csv",
  );
}

export function FileDrop({ onFiles }: { onFiles: (files: File[]) => void }) {
  const [dragging, setDragging] = useState(false);

  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    const files = csvFiles(event.dataTransfer.files);
    if (files.length > 0) {
      onFiles(files);
    }
  };

  return (
    <label
      className={dragging ? "up-drop dragging" : "up-drop"}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <input
        type="file"
        multiple
        accept=".csv,text/csv"
        onChange={(event) => {
          onFiles(csvFiles(event.target.files));
          event.target.value = "";
        }}
      />
      <span className="up-drop-title">
        Drop CSV files or <span className="up-underline">browse</span>
      </span>
      <span className="up-drop-note">
        Multiple files per batch &middot; originals are stored unchanged
      </span>
    </label>
  );
}
