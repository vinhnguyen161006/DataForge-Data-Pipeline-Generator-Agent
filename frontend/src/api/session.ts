const TOKEN_KEY = "dataforge.token";
const ACCOUNT_KEY = "dataforge.account";

const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) {
    listener();
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string, accountEmail: string): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(ACCOUNT_KEY, accountEmail);
  notify();
}

export function getAccountEmail(): string | null {
  return localStorage.getItem(ACCOUNT_KEY);
}

export function clearToken(): void {
  if (getToken() === null) {
    return;
  }
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(ACCOUNT_KEY);
  notify();
}

export function subscribeToken(listener: () => void): () => void {
  const onStorage = (event: StorageEvent) => {
    if (event.key === TOKEN_KEY) {
      listener();
    }
  };
  listeners.add(listener);
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}
