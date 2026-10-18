import { ApiError, login } from "./client";
import { setToken } from "./session";

export type AuthFailure = "network" | "unauthorized" | "forbidden" | "rate_limited" | "other";

interface AuthAdapter {
  kind: "mock" | "api";
  signIn(email: string, password: string): Promise<void>;
}

export const DEMO_EMAIL = "linh@retail.co";
export const DEMO_PASSWORD = "dataforge-demo";

const MOCK_DELAY_MS = 900;
const MOCK_TOKEN = "dev-mock-token";
const HTTP_UNAUTHORIZED = 401;
const HTTP_FORBIDDEN = 403;
const HTTP_TOO_MANY = 429;

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

const mockAuthAdapter: AuthAdapter = {
  kind: "mock",
  async signIn(email, password) {
    await wait(MOCK_DELAY_MS);
    if (/offline/i.test(email)) {
      throw new TypeError("Mock network failure");
    }
    if (email.toLowerCase() !== DEMO_EMAIL || password !== DEMO_PASSWORD) {
      throw new ApiError(HTTP_UNAUTHORIZED, "Incorrect email or password");
    }
    setToken(MOCK_TOKEN, email);
  },
};

const apiAuthAdapter: AuthAdapter = {
  kind: "api",
  signIn: login,
};

export const usesMockAuth = import.meta.env.DEV && import.meta.env.VITE_AUTH_ADAPTER !== "api";

export const authAdapter: AuthAdapter = usesMockAuth ? mockAuthAdapter : apiAuthAdapter;

export function authFailure(caught: unknown): AuthFailure {
  if (caught instanceof TypeError) {
    return "network";
  }
  if (!(caught instanceof ApiError)) {
    return "other";
  }
  switch (caught.status) {
    case HTTP_UNAUTHORIZED:
      return "unauthorized";
    case HTTP_FORBIDDEN:
      return "forbidden";
    case HTTP_TOO_MANY:
      return "rate_limited";
    default:
      return "other";
  }
}
