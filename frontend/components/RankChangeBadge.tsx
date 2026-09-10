// "—" when there's no prior-day rank to compare against (a new top-5
// entrant) or when the rank didn't change; a real change earns a colored
// ↑N/↓N — this way the column always renders something, never an
// inconsistently empty cell next to populated ones.
export function RankChangeBadge({
  currentRank,
  previousRank,
}: {
  currentRank: number;
  previousRank: number | null;
}) {
  if (previousRank === null || previousRank === currentRank) {
    return <span className="font-mono-tabular text-xs text-ink-dim">—</span>;
  }

  const improved = currentRank < previousRank;
  const delta = Math.abs(previousRank - currentRank);

  return (
    <span
      className={"font-mono-tabular text-xs font-semibold " + (improved ? "text-green" : "text-negative")}
    >
      {improved ? "↑" : "↓"}
      {delta}
    </span>
  );
}
