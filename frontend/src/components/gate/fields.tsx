import { type KeyboardEvent, type ReactNode, useId, useState } from "react";

export function TextField({
  label,
  value,
  onChange,
  mono = false,
  multiline = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  mono?: boolean;
  multiline?: boolean;
}) {
  const id = useId();
  const className = mono ? "gt-input lp-mono" : "gt-input";
  return (
    <div className="gt-field">
      <label htmlFor={id}>{label}</label>
      {multiline ? (
        <textarea
          id={id}
          className={className}
          rows={2}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <input
          id={id}
          className={className}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </div>
  );
}

export function SelectField<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly T[];
  onChange: (value: T) => void;
}) {
  return (
    <label className="gt-field">
      <span>{label}</span>
      <select
        className="gt-input"
        value={value}
        onChange={(event) => onChange(event.target.value as T)}
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option.replaceAll("_", " ")}
          </option>
        ))}
      </select>
    </label>
  );
}

export function ListField({
  label,
  value,
  onChange,
  placeholder = "Type and press Enter",
}: {
  label: string;
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState("");

  const commit = () => {
    const item = draft.trim();
    if (item && !value.includes(item)) {
      onChange([...value, item]);
    }
    setDraft("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      commit();
    } else if (event.key === "Backspace" && draft === "" && value.length > 0) {
      onChange(value.slice(0, -1));
    }
  };

  return (
    <div className="gt-field">
      <span>{label}</span>
      <div className="gt-chips">
        {value.map((item) => (
          <span key={item} className="gt-chip">
            <span className="lp-mono">{item}</span>
            <button
              type="button"
              aria-label={`Remove ${item}`}
              onClick={() => onChange(value.filter((other) => other !== item))}
            >
              &times;
            </button>
          </span>
        ))}
        <input
          aria-label={label}
          value={draft}
          placeholder={value.length === 0 ? placeholder : ""}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          onBlur={commit}
        />
      </div>
    </div>
  );
}

function newId(): string {
  return crypto.randomUUID();
}

export function ListEditor<T>({
  items,
  onChange,
  blank,
  noun,
  minimum = 0,
  render,
}: {
  items: T[];
  onChange: (items: T[]) => void;
  blank: () => T;
  noun: string;
  minimum?: number;
  render: (item: T, update: (item: T) => void) => ReactNode;
}) {
  const [ids, setIds] = useState<string[]>(() => items.map(newId));
  const keys = ids.length === items.length ? ids : items.map(newId);
  const removable = items.length > minimum;

  const update = (position: number, item: T) =>
    onChange(items.map((current, at) => (at === position ? item : current)));

  const remove = (position: number) => {
    setIds(keys.filter((_, at) => at !== position));
    onChange(items.filter((_, at) => at !== position));
  };

  const add = () => {
    setIds([...keys, newId()]);
    onChange([...items, blank()]);
  };

  return (
    <div className="gt-list">
      {items.map((item, position) => (
        <div key={keys[position]} className="gt-item">
          <div className="gt-item-head">
            <span className="gt-item-index">
              {noun} {position + 1}
            </span>
            <button
              type="button"
              className="ws-link"
              disabled={!removable}
              onClick={() => remove(position)}
            >
              Remove
            </button>
          </div>
          {render(item, (next) => update(position, next))}
        </div>
      ))}
      <button type="button" className="gt-add" onClick={add}>
        + Add {noun}
      </button>
    </div>
  );
}
