import { type SubmitEvent, useState } from "react";
import { ApiError, answerClarifications } from "../../api/client";
import type { ClarificationQuestion, Run } from "../../api/types";
import { formatSavedAt, useRunWork } from "../../hooks/useRunWork";
import { LoadError } from "../workspace/LoadError";

const OTHER = "__other__";
const HTTP_CONFLICT = 409;

interface Draft {
  choice: string | null;
  other: string;
}

function isDraftList(value: unknown): value is Draft[] {
  return (
    Array.isArray(value) &&
    value.every(
      (item) =>
        typeof item === "object" &&
        item !== null &&
        "other" in item &&
        typeof item.other === "string" &&
        "choice" in item &&
        (item.choice === null || typeof item.choice === "string"),
    )
  );
}

function noAnswers(drafts: Draft[]): boolean {
  return drafts.every((draft) => draft.choice === null && draft.other.trim() === "");
}

function answerOf(question: ClarificationQuestion, draft: Draft): string {
  if (question.options.length === 0 || draft.choice === OTHER) {
    return draft.other.trim();
  }
  return draft.choice ?? "";
}

function QuestionField({
  question,
  index,
  draft,
  disabled,
  onChange,
}: {
  question: ClarificationQuestion;
  index: number;
  draft: Draft;
  disabled: boolean;
  onChange: (draft: Draft) => void;
}) {
  const name = `clarify-${index}`;
  const freeText = question.options.length === 0 || draft.choice === OTHER;
  return (
    <fieldset className="rn-clarify" disabled={disabled}>
      <legend>
        Clarification needed &middot; {question.topic} &middot; question {index + 1}
      </legend>
      <p className="rn-clarify-question">{question.question}</p>
      <p className="rn-clarify-why">{question.why}</p>
      {question.options.map((option) => (
        <label key={option} className="rn-option">
          <input
            type="radio"
            name={name}
            checked={draft.choice === option}
            onChange={() => onChange({ ...draft, choice: option })}
          />
          <span>{option}</span>
        </label>
      ))}
      {question.options.length > 0 && (
        <label className="rn-option">
          <input
            type="radio"
            name={name}
            checked={draft.choice === OTHER}
            onChange={() => onChange({ ...draft, choice: OTHER })}
          />
          <span>Other</span>
        </label>
      )}
      {freeText && (
        <textarea
          className="up-textarea rn-clarify-text"
          rows={2}
          aria-label={`Answer to: ${question.question}`}
          placeholder="Your answer"
          value={draft.other}
          onChange={(event) => onChange({ ...draft, other: event.target.value })}
        />
      )}
    </fieldset>
  );
}

export function ClarificationPanel({
  projectId,
  runId,
  interruptId,
  questions,
  canAnswer,
  onAnswered,
  onStale,
}: {
  projectId: string;
  runId: string;
  interruptId: string;
  questions: ClarificationQuestion[];
  canAnswer: boolean;
  onAnswered: (run: Run) => void;
  onStale: () => void;
}) {
  const work = useRunWork<Draft[]>(
    runId,
    `clarify:${interruptId}`,
    () => questions.map(() => ({ choice: null, other: "" })),
    (value): value is Draft[] => isDraftList(value) && value.length === questions.length,
    noAnswers,
  );
  const drafts = work.value;
  const setDrafts = work.setValue;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const answers = questions.map((question, index) => answerOf(question, drafts[index]));
  const missing = answers.filter((answer) => answer.length === 0).length;

  const onSubmit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = questions.map((question, index) => ({
        question: question.question,
        answer: answers[index],
      }));
      const next = await answerClarifications(projectId, runId, interruptId, body);
      work.clear();
      onAnswered(next);
    } catch (caught) {
      setBusy(false);
      if (caught instanceof ApiError && caught.status === HTTP_CONFLICT) {
        onStale();
        return;
      }
      setError(caught);
    }
  };

  return (
    <section className="ws-page rn-page">
      <div>
        <h1 className="ws-h1">Questions from the Modeler</h1>
        <p className="ws-lede">
          The profile alone cannot settle these points, so the Modeler asks instead of guessing.
          Your answers go back to it before it proposes a design.
        </p>
      </div>
      {work.restoredAt && (
        <div className="ws-banner notice">
          Your unsent answers from {formatSavedAt(work.restoredAt)} were restored.
        </div>
      )}
      {!canAnswer && (
        <div className="ws-banner notice">Answering design questions is an Engineer action.</div>
      )}
      <form className="rn-clarify-form" onSubmit={onSubmit} aria-busy={busy}>
        {questions.map((question, index) => (
          <QuestionField
            key={question.question}
            question={question}
            index={index}
            draft={drafts[index]}
            disabled={!canAnswer || busy}
            onChange={(draft) =>
              setDrafts((current) => current.map((item, at) => (at === index ? draft : item)))
            }
          />
        ))}
        {error !== null && <LoadError error={error} />}
        {canAnswer && (
          <div className="rn-actions">
            <button type="submit" className="lp-button small" disabled={missing > 0 || busy}>
              {busy ? "Sending..." : "Send answers to the Modeler"}
            </button>
            {missing > 0 && (
              <span className="ws-muted">
                {missing} question{missing === 1 ? "" : "s"} still need an answer.
              </span>
            )}
          </div>
        )}
      </form>
    </section>
  );
}
