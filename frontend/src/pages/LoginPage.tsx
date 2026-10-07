import { type SubmitEvent, useState } from "react";
import { login, register } from "../api/client";
import { errorText } from "../errors";

type Mode = "signIn" | "register";

const COPY: Record<Mode, { title: string; submit: string; switchLabel: string }> = {
  signIn: { title: "Sign in", submit: "Sign in", switchLabel: "Create an account" },
  register: {
    title: "Create account",
    submit: "Create account",
    switchLabel: "I already have an account",
  },
};

export function LoginPage() {
  const [mode, setMode] = useState<Mode>("signIn");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const copy = COPY[mode];

  const onSubmit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await (mode === "signIn" ? login(email, password) : register(email, password));
    } catch (caught) {
      setError(errorText(caught));
      setSubmitting(false);
    }
  };

  const switchMode = () => {
    setMode(mode === "signIn" ? "register" : "signIn");
    setError(null);
  };

  return (
    <section className="page narrow">
      <h2>{copy.title}</h2>
      <form className="form" onSubmit={onSubmit}>
        <label>
          Email
          <input
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
        <label>
          Password
          <input
            type="password"
            autoComplete={mode === "signIn" ? "current-password" : "new-password"}
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="primary" disabled={submitting}>
          {submitting ? "Please wait..." : copy.submit}
        </button>
      </form>
      <button type="button" className="link" onClick={switchMode}>
        {copy.switchLabel}
      </button>
    </section>
  );
}
