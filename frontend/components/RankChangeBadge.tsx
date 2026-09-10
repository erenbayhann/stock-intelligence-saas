// Renders nothing when there's no prior-day rank to compare against (a new
// top-5 entrant) or when the rank didn't change — only a real change earns
// a badge.
export function RankChangeBadge({
  currentRank,
  previousRank,
}: {
  currentRank: number;
  previousRank: number | null;
}) {
  if (previousRank === null || previousRank === currentRank) return null;

  const improved = currentRank < previousRank;
  const delta = Math.abs(previousRank - currentRank);

  return (
    <span
      className={
        "font-mono-tabular text-[11px] font-semibold ml-1.5 " + (improved ? "text-green" : "text-negative")
      }
    >
      {improved ? "↑" : "↓"}
      {delta}
    </span>
  );
}
