export function ResultBadge({ correct }: { correct: boolean | null }) {
  if (correct === null) {
    return <span className="font-mono-tabular text-xs text-ink-faint">Session pending</span>;
  }
  return (
    <span
      className={
        "flex items-center gap-1 font-mono-tabular text-xs " +
        (correct ? "text-green" : "text-negative")
      }
    >
      {correct ? (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
          <path d="M5 13l4 4L19 7" />
        </svg>
      ) : (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      )}
      {correct ? "Correct" : "Incorrect"}
    </span>
  );
}

export function DirectionBadge({ bullish = true }: { bullish?: boolean }) {
  return (
    <span className="flex items-center gap-1 font-mono-tabular text-sm text-green">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6">
        <path d="M6 18L18 6M18 6H9M18 6V15" />
      </svg>
      {bullish ? "Bullish" : "Bearish"}
    </span>
  );
}

export function SignedValue({ value, digits = 1 }: { value: number | null; digits?: number }) {
  if (value === null || value === undefined) {
    return <span className="font-mono-tabular text-sm text-ink-faint">—</span>;
  }
  const pct = value * 100;
  const positive = pct >= 0;
  return (
    <span className={"font-mono-tabular text-sm " + (positive ? "text-green" : "text-negative")}>
      {positive ? "+" : "−"}
      {Math.abs(pct).toFixed(digits)}%
    </span>
  );
}
