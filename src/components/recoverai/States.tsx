export function LoadingState() {
  return <div className="state-card">Loading RecoverAI demo data...</div>;
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="state-card error-state">
      <strong>Unable to load RecoverAI dashboard</strong>
      <span>{message}</span>
    </div>
  );
}
