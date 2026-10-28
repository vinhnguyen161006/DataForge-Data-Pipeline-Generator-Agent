import { useState } from "react";
import type { BuildAttempt, ExecutionReport } from "../../api/types";
import { formatBytes, formatClock, formatCount, formatSeconds } from "../../format";

const MODEL_PASSED = "success";
const TEST_PASSED = "pass";
const NOT_MEASURED = "n/a";

type Tone = "ok" | "bad" | "muted";

interface LogEntry {
  key: string;
  at: string;
  text: string;
  tone: Tone;
}

function counted(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

function failedModels(report: ExecutionReport): number {
  return report.models.filter((model) => model.status !== MODEL_PASSED).length;
}

function failedTests(report: ExecutionReport): number {
  return report.tests.filter((test) => test.status !== TEST_PASSED).length;
}

function buildPassed(report: ExecutionReport): boolean {
  return (
    report.compiled && report.succeeded && failedModels(report) === 0 && failedTests(report) === 0
  );
}

function originText(attempt: BuildAttempt): string {
  if (attempt.origin === "optimizer") {
    return `Optimizer rewrite saved as v${attempt.version}`;
  }
  if (attempt.origin === "user_edit") {
    return `Engineer edit saved as v${attempt.version}`;
  }
  if (attempt.version === 1) {
    return "Codegen wrote v1 from the approved design";
  }
  return `Codegen repaired the models as v${attempt.version}`;
}

function outcomeText(attempt: BuildAttempt): { text: string; tone: Tone } {
  const report = attempt.report;
  if (report === null) {
    return { text: `v${attempt.version}: the sandbox job did not finish`, tone: "bad" };
  }
  if (buildPassed(report)) {
    const models = counted(report.models.length, "model");
    const tests = counted(report.tests.length, "test");
    return {
      text: `v${attempt.version} built in ${formatSeconds(report.total_seconds)}: ${models}, ${tests} passed`,
      tone: "ok",
    };
  }
  if (!report.compiled) {
    return { text: `v${attempt.version}: dbt compile failed`, tone: "bad" };
  }
  return {
    text: `v${attempt.version} failed: ${counted(failedModels(report), "model")} and ${counted(failedTests(report), "test")} did not pass`,
    tone: "bad",
  };
}

function logEntries(attempts: BuildAttempt[]): LogEntry[] {
  const entries: LogEntry[] = [];
  for (const attempt of attempts) {
    const id = attempt.code_version_id;
    entries.push({
      key: `${id}-gen`,
      at: attempt.generated_at,
      text: originText(attempt),
      tone: "muted",
    });
    if (attempt.queued_at !== null) {
      entries.push({
        key: `${id}-queued`,
        at: attempt.queued_at,
        text: `v${attempt.version} queued for a sandbox build`,
        tone: "muted",
      });
    }
    if (attempt.finished_at !== null) {
      entries.push({ key: `${id}-done`, at: attempt.finished_at, ...outcomeText(attempt) });
    }
  }
  return entries.sort((left, right) => left.at.localeCompare(right.at));
}

function Log({ attempts }: { attempts: BuildAttempt[] }) {
  return (
    <ol className="rn-log" aria-label="Build log">
      {logEntries(attempts).map((entry) => (
        <li key={entry.key} className={`rn-log-entry ${entry.tone}`}>
          <time className="rn-log-time" dateTime={entry.at}>
            {formatClock(entry.at)}
          </time>
          <span>{entry.text}</span>
        </li>
      ))}
    </ol>
  );
}

function statusTone(status: string, passed: string): Tone {
  if (status === passed) {
    return "ok";
  }
  return status === "skipped" ? "muted" : "bad";
}

function Measured({ value, format }: { value: number | null; format: (value: number) => string }) {
  if (value === null) {
    return (
      <span className="rn-faint" title="Not measured for this model">
        {NOT_MEASURED}
      </span>
    );
  }
  return <>{format(value)}</>;
}

function ModelTable({ report }: { report: ExecutionReport }) {
  if (report.models.length === 0) {
    return <p className="ws-muted">No model ran in this build.</p>;
  }
  return (
    <div className="rn-table-wrap">
      <table className="rn-table">
        <caption className="rn-caption">Models</caption>
        <thead>
          <tr>
            <th scope="col">Model</th>
            <th scope="col">Status</th>
            <th scope="col" className="num">
              Time
            </th>
            <th scope="col" className="num">
              Rows scanned
            </th>
            <th scope="col" className="num">
              Peak memory
            </th>
          </tr>
        </thead>
        <tbody>
          {report.models.map((model) => (
            <tr key={model.model_name}>
              <td>{model.model_name}</td>
              <td className={`rn-status ${statusTone(model.status, MODEL_PASSED)}`}>
                {model.status}
              </td>
              <td className="num">{formatSeconds(model.seconds)}</td>
              <td className="num">
                <Measured value={model.rows_scanned} format={formatCount} />
              </td>
              <td className="num">
                <Measured value={model.peak_memory_bytes} format={formatBytes} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TestTable({ report }: { report: ExecutionReport }) {
  if (report.tests.length === 0) {
    return <p className="ws-muted">No test ran in this build.</p>;
  }
  return (
    <div className="rn-table-wrap">
      <table className="rn-table">
        <caption className="rn-caption">
          Tests &middot; {report.tests.length - failedTests(report)} of {report.tests.length} passed
        </caption>
        <thead>
          <tr>
            <th scope="col">Test</th>
            <th scope="col">Model</th>
            <th scope="col">Status</th>
            <th scope="col" className="num">
              Failing rows
            </th>
          </tr>
        </thead>
        <tbody>
          {report.tests.map((test) => (
            <tr key={`${test.model_name}-${test.test_name}`}>
              <td>{test.test_name}</td>
              <td>{test.model_name}</td>
              <td className={`rn-status ${statusTone(test.status, TEST_PASSED)}`}>{test.status}</td>
              <td className="num">{formatCount(test.failures)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Quarantine({ counts }: { counts: Record<string, number> }) {
  const entries = Object.entries(counts).filter(([, count]) => count > 0);
  if (entries.length === 0) {
    return null;
  }
  return (
    <p className="rn-quarantine">
      Quarantined rows:{" "}
      {entries.map(([model, count]) => `${model} ${formatCount(count)}`).join(", ")}
    </p>
  );
}

function AttemptDetail({ attempt }: { attempt: BuildAttempt }) {
  const report = attempt.report;
  if (report === null) {
    const waiting = attempt.job_status === "queued" || attempt.job_status === "running";
    return (
      <p className="ws-muted">
        {waiting
          ? "This version is waiting for its sandbox build. Measurements appear here when it finishes."
          : "The sandbox job for this version stopped without a report."}
      </p>
    );
  }
  return (
    <div className="rn-attempt">
      {report.error !== null && <pre className="rn-error">{report.error}</pre>}
      <ModelTable report={report} />
      <TestTable report={report} />
      <Quarantine counts={report.quarantine_counts} />
    </div>
  );
}

function versionLabel(attempt: BuildAttempt): string {
  if (attempt.report === null) {
    return `v${attempt.version}`;
  }
  return `v${attempt.version} ${buildPassed(attempt.report) ? "passed" : "failed"}`;
}

export function BuildLog({ attempts }: { attempts: BuildAttempt[] }) {
  const latest = attempts[attempts.length - 1];
  const [chosen, setChosen] = useState<string | null>(null);
  const selected = attempts.find((attempt) => attempt.code_version_id === chosen) ?? latest;

  return (
    <section className="rn-builds" aria-labelledby="rn-builds-title">
      <div>
        <h2 id="rn-builds-title" className="ws-h2">
          Sandbox builds
        </h2>
        <p className="gt-hint">
          Each code version is compiled and tested with dbt on DuckDB inside the sandbox. Pass or
          fail comes from dbt itself, never from the model that wrote the code.
        </p>
      </div>
      <Log attempts={attempts} />
      <div className="gt-tabs" role="tablist" aria-label="Code versions">
        {attempts.map((attempt) => (
          <button
            key={attempt.code_version_id}
            type="button"
            role="tab"
            className="gt-tab"
            aria-selected={attempt.code_version_id === selected.code_version_id}
            onClick={() => setChosen(attempt.code_version_id)}
          >
            {versionLabel(attempt)}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        <AttemptDetail attempt={selected} />
      </div>
    </section>
  );
}
