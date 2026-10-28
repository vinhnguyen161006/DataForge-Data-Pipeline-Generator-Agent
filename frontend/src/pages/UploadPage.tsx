import "../upload.css";
import { type ReactNode, useEffect, useState } from "react";
import { createRun, markBatchReady } from "../api/client";
import { FileDrop } from "../components/upload/FileDrop";
import { FileList } from "../components/upload/FileList";
import { PreviewTable } from "../components/upload/PreviewTable";
import { ReadConfigPanel } from "../components/upload/ReadConfigPanel";
import { LoadError } from "../components/workspace/LoadError";
import { type FileEntry, savedFilesOf, useBatchUpload } from "../hooks/useBatchUpload";
import { useProject } from "../hooks/useProjects";
import { discardDraft, readDraft, rememberRun, saveDraft, type UploadDraft } from "../progress";
import { navigate } from "../router";

const MIN_REQUIREMENT_LENGTH = 10;

function blockReason(
  entries: FileEntry[],
  batchComplete: boolean,
  requirement: string,
): ReactNode | null {
  if (entries.length === 0) {
    return "Add at least one CSV file to the batch.";
  }
  if (entries.some((entry) => entry.status === "uploading")) {
    return "Wait until every file has finished uploading.";
  }
  if (entries.some((entry) => entry.status === "failed")) {
    return "Retry failed files, or discard the draft to choose a different file set.";
  }
  const unconfirmed = entries.filter((entry) => entry.status !== "confirmed").length;
  if (unconfirmed > 0) {
    return `Confirm the read configuration of every file (${unconfirmed} left).`;
  }
  if (!batchComplete) {
    return <>Mark the batch as complete &mdash; multi-file batches never start early.</>;
  }
  if (requirement.trim().length < MIN_REQUIREMENT_LENGTH) {
    return `Describe the analytical requirement (${MIN_REQUIREMENT_LENGTH}+ characters).`;
  }
  return null;
}

export function UploadPage({ projectId }: { projectId: string }) {
  const [generation, setGeneration] = useState(0);
  const discard = () => {
    discardDraft(projectId);
    setGeneration((current) => current + 1);
  };
  return (
    <UploadForm
      key={generation}
      projectId={projectId}
      initial={readDraft(projectId)}
      onDiscard={discard}
    />
  );
}

function UploadForm({
  projectId,
  initial,
  onDiscard,
}: {
  projectId: string;
  initial: UploadDraft | null;
  onDiscard: () => void;
}) {
  const project = useProject(projectId);
  const upload = useBatchUpload(projectId, initial);
  const [requirement, setRequirement] = useState(initial?.requirement ?? "");
  const [batchComplete, setBatchComplete] = useState(initial?.batchComplete ?? false);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<unknown>(null);
  const reason = blockReason(upload.entries, batchComplete, requirement);
  const selected = upload.selected;
  const { entries, knownBatchId } = upload;
  const hasDraft = entries.length > 0 || requirement.trim().length > 0 || batchComplete;

  useEffect(() => {
    if (starting) {
      return;
    }
    const files = savedFilesOf(entries);
    if (files.length === 0 && requirement.trim().length === 0 && !batchComplete) {
      discardDraft(projectId);
      return;
    }
    saveDraft({ projectId, batchId: knownBatchId, files, requirement, batchComplete });
  }, [projectId, entries, knownBatchId, requirement, batchComplete, starting]);

  const onStart = async () => {
    setStarting(true);
    setStartError(null);
    try {
      const batchId = await upload.batchId();
      await markBatchReady(projectId, batchId);
      const run = await createRun(projectId, batchId, requirement.trim());
      rememberRun(projectId, run.id, requirement.trim());
      discardDraft(projectId);
      navigate({ name: "run", projectId, runId: run.id });
    } catch (caught) {
      setStartError(caught);
      setStarting(false);
    }
  };

  return (
    <section className="ws-page up-page">
      <div className="ws-crumb">{project?.name ?? "Project"} / Upload &amp; requirement</div>
      <div className="ws-title-row">
        <div>
          <h1 className="ws-h1">Upload &amp; requirement</h1>
          <p className="ws-lede">
            Add the CSV files for this batch and describe what you need. Original files and the read
            configuration are preserved with the batch. Your progress is saved on this device.
          </p>
        </div>
        {hasDraft && !starting && (
          <button type="button" className="ws-button-outline" onClick={onDiscard}>
            Discard draft
          </button>
        )}
      </div>

      <div className="up-columns">
        <div className="up-column">
          <FileDrop onFiles={upload.addFiles} />
          <p className="ws-muted">
            Choose the complete file set together. Discard the draft to change its file list.
          </p>
          <FileList
            entries={upload.entries}
            selectedKey={selected?.key ?? null}
            onSelect={upload.select}
            onRetry={upload.retry}
            onRemove={upload.remove}
            canRemove={upload.knownBatchId === null}
          />
          <label className="up-check up-complete">
            <input
              type="checkbox"
              checked={batchComplete}
              onChange={(event) => setBatchComplete(event.target.checked)}
            />
            <span>
              This batch is complete
              <span className="up-check-note">
                Profiling waits until every file in a multi-file batch is present and marked ready.
              </span>
            </span>
          </label>
        </div>

        <div className="up-column">
          <label htmlFor="requirement" className="up-label">
            Analytical requirement <span className="up-required">*</span>
          </label>
          <textarea
            id="requirement"
            className="up-textarea"
            rows={5}
            value={requirement}
            placeholder="Weekly pass rate by module and presentation, split by region. Exclude withdrawn students."
            onChange={(event) => setRequirement(event.target.value)}
          />
          <ReadConfigPanel
            entry={selected}
            onChange={(draft) => selected && upload.editDraft(selected.key, draft)}
            onConfirm={() => selected && upload.confirm(selected.key)}
          />
        </div>
      </div>

      {selected?.source && <PreviewTable source={selected.source} />}

      {startError !== null && <LoadError error={startError} />}

      <div className="up-start">
        <button
          type="button"
          className="lp-button small"
          disabled={reason !== null || starting}
          aria-describedby={reason ? "why-blocked" : undefined}
          onClick={onStart}
        >
          {starting ? "Starting..." : "Start profiling"}
        </button>
        {reason && (
          <span id="why-blocked" className="ws-muted">
            {reason}
          </span>
        )}
      </div>
    </section>
  );
}
