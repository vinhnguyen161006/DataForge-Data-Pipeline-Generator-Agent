import { useSyncExternalStore } from "react";
import { getToken, subscribeToken } from "../api/session";

export function useAuthToken(): string | null {
  return useSyncExternalStore(subscribeToken, getToken);
}
