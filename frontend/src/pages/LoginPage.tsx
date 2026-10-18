import "../landing.css";
import "../login.css";
import { type ReactNode, type SubmitEvent, useRef, useState } from "react";
import {
  type AuthFailure,
  authAdapter,
  authFailure,
  DEMO_EMAIL,
  DEMO_PASSWORD,
  usesMockAuth,
} from "../api/auth";
import { Logo } from "../components/landing/Logo";
import { navigate } from "../router";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const FAILURE_TEXT: Record<AuthFailure, ReactNode> = {
  network: <>We can&rsquo;t reach DataForge right now. Check your connection and try again.</>,
  unauthorized: <>That email and password don&rsquo;t match an account.</>,
  rate_limited: <>Too many attempts. Wait a minute, then try again.</>,
  forbidden: <>Your account doesn&rsquo;t have access to this workspace.</>,
  other: <>Sign-in failed. Try again, or contact your administrator if it continues.</>,
};

function emailError(email: string): string {
  const value = email.trim();
  if (!value) {
    return "Enter your email address.";
  }
  return EMAIL_PATTERN.test(value) ? "" : "Enter a valid email address, like name@company.com.";
}

function passwordError(password: string): string {
  return password ? "" : "Enter your password.";
}

function LayersArt() {
  return (
    <div className="lg-art" aria-hidden="true">
      <div className="lp-eyebrow">BRONZE &middot; SILVER &middot; MARTS</div>
      <svg viewBox="0 0 520 380" aria-hidden="true">
        <g stroke="#958D84" strokeWidth="1.1" fill="none">
          <path d="M150 92 C 210 92, 210 190, 260 190" />
          <path d="M150 190 L 260 190" />
          <path d="M150 288 C 210 288, 210 190, 260 190" />
          <path d="M380 190 L 430 190" />
        </g>
        <g fill="#FFFFFF" stroke="#D9CEC1">
          <rect x="20" y="62" width="130" height="60" />
          <rect x="20" y="160" width="130" height="60" />
          <rect x="20" y="258" width="130" height="60" />
        </g>
        <g fill="#E8E1D9">
          <rect x="34" y="80" width="80" height="5" />
          <rect x="34" y="94" width="56" height="5" />
          <rect x="34" y="178" width="88" height="5" />
          <rect x="34" y="192" width="48" height="5" />
          <rect x="34" y="276" width="70" height="5" />
          <rect x="34" y="290" width="60" height="5" />
        </g>
        <rect x="260" y="150" width="120" height="80" fill="#111111" />
        <rect x="276" y="170" width="76" height="5" fill="#FFFFFF" />
        <g fill="#77716B">
          <rect x="276" y="184" width="52" height="5" />
          <rect x="276" y="198" width="64" height="5" />
        </g>
        <rect x="430" y="160" width="70" height="14" fill="#111111" />
        <rect x="438" y="178" width="54" height="14" fill="#77716B" />
        <rect x="446" y="196" width="38" height="14" fill="#E6D1BB" />
      </svg>
      <p className="lg-quote">Every approval binds to an exact version.</p>
    </div>
  );
}

function MockAdapterNote() {
  return (
    <div className="lg-dev">
      <span className="lg-dev-label">DEV MOCK AUTH ADAPTER &mdash; NOT REAL AUTHENTICATION</span>
      <span>
        Demo account <span className="lg-code">{DEMO_EMAIL}</span> /{" "}
        <span className="lg-code">{DEMO_PASSWORD}</span>. Use any other password to see the 401
        state, or an address containing <span className="lg-code">offline</span> for a network
        error.
      </span>
    </div>
  );
}

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<AuthFailure | null>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  const emailMessage = touched ? emailError(email) : "";
  const passwordMessage = touched ? passwordError(password) : "";
  const goToSite = () => navigate({ name: "landing" });

  const onSubmit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy) {
      return;
    }
    setTouched(true);
    setFailure(null);
    const badEmail = emailError(email) !== "";
    if (badEmail || passwordError(password) !== "") {
      window.setTimeout(() => (badEmail ? emailRef : passwordRef).current?.focus(), 0);
      return;
    }
    setBusy(true);
    try {
      await authAdapter.signIn(email.trim(), password);
    } catch (caught) {
      setBusy(false);
      setPassword("");
      setFailure(authFailure(caught));
      window.setTimeout(() => passwordRef.current?.focus(), 0);
    }
  };

  return (
    <div className="lp lg">
      <div className="lg-main">
        <div className="lg-top">
          <button type="button" className="lp-brand" aria-label="DataForge home" onClick={goToSite}>
            <Logo />
            <span className="lp-brand-name">DataForge</span>
          </button>
          <button type="button" className="lg-back" onClick={goToSite}>
            &larr; Back to site
          </button>
        </div>

        <div className="lg-center">
          <div className="lg-panel">
            <h1>Welcome back.</h1>
            <p className="lg-lede">
              Sign in to review designs, verify pipelines and approve what gets published.
            </p>

            {failure && (
              <div role="alert" className="lg-banner error">
                {FAILURE_TEXT[failure]}
              </div>
            )}

            <form className="lg-form" noValidate aria-busy={busy} onSubmit={onSubmit}>
              <div className="lg-field">
                <label htmlFor="lg-email">Email</label>
                <input
                  id="lg-email"
                  ref={emailRef}
                  className="lg-input"
                  type="email"
                  inputMode="email"
                  autoComplete="username"
                  value={email}
                  disabled={busy}
                  aria-invalid={emailMessage !== ""}
                  aria-describedby="lg-email-err"
                  onChange={(event) => setEmail(event.target.value)}
                />
                {emailMessage && (
                  <span id="lg-email-err" className="lg-field-error">
                    {emailMessage}
                  </span>
                )}
              </div>

              <div className="lg-field">
                <label htmlFor="lg-pw">Password</label>
                <div className="lg-secret">
                  <input
                    id="lg-pw"
                    ref={passwordRef}
                    className="lg-input"
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    value={password}
                    disabled={busy}
                    aria-invalid={passwordMessage !== ""}
                    aria-describedby="lg-pw-err"
                    onChange={(event) => setPassword(event.target.value)}
                  />
                  <button
                    type="button"
                    className="lg-toggle"
                    aria-controls="lg-pw"
                    aria-pressed={showPassword}
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    onClick={() => setShowPassword(!showPassword)}
                  >
                    {showPassword ? "Hide" : "Show"}
                  </button>
                </div>
                {passwordMessage && (
                  <span id="lg-pw-err" className="lg-field-error">
                    {passwordMessage}
                  </span>
                )}
              </div>

              <button type="submit" className="lg-submit" disabled={busy}>
                {busy ? <>Signing in&hellip;</> : "Sign In"}
              </button>
            </form>

            <p className="lg-help">
              Access is granted by your workspace administrator. Forgot your password? Ask your
              administrator to reset it.
            </p>

            {usesMockAuth && <MockAdapterNote />}
          </div>
        </div>

        <div className="lg-legal">
          <span>&copy; 2026 DataForge</span>
          <span>Privacy &middot; Terms</span>
        </div>
      </div>
      <LayersArt />
    </div>
  );
}
