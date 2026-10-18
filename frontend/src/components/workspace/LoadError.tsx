import type { ReactNode } from "react";
import { ApiError } from "../../api/client";

const HTTP_FORBIDDEN = 403;
const HTTP_SERVER_ERROR = 500;

export function describeError(caught: unknown): ReactNode {
  if (caught instanceof TypeError) {
    return <>We can&rsquo;t reach DataForge right now. Check your connection and try again.</>;
  }
  if (caught instanceof ApiError && caught.status >= HTTP_SERVER_ERROR) {
    return (
      <>
        DataForge isn&rsquo;t responding ({caught.status}). Check that the backend is running, then
        retry.
      </>
    );
  }
  if (caught instanceof ApiError && caught.status === HTTP_FORBIDDEN) {
    return <>Your account doesn&rsquo;t have access to this workspace.</>;
  }
  return caught instanceof Error ? caught.message : String(caught);
}

export function LoadError({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="ws-banner error">
      <span>{describeError(error)}</span>
      {onRetry && (
        <button type="button" className="ws-link" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}
