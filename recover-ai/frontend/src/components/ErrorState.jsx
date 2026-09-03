export function ErrorState({ message }) {
  return (
    <div className="state-card error-state">
      <strong>Unable to load dashboard</strong>
      <span>{message}</span>
    </div>
  )
}
