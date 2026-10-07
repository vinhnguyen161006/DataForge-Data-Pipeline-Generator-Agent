export function RunPage({ projectId, runId }: { projectId: string; runId: string }) {
  return (
    <section className="page">
      <h2>Run</h2>
      <p className="todo">
        TODO: poll run status with useRunPolling and render the pending step: clarification form,
        DesignGatePage, running job, CodeGatePage (lazy-loaded because it pulls in Monaco),
        published links.
      </p>
    </section>
  );
}
