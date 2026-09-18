// Matches the backend's _NEUTRAL_SENTIMENT_THRESHOLD (app/services/news_service.py).
export const NEUTRAL_SENTIMENT_THRESHOLD = 0.15;

// Neutral labels by design — "Bullish/Bearish" reads as a directional trading
// call, which this isn't. This describes the tone of a single headline, not
// a recommendation.
export function SentimentBadge({ sentiment }: { sentiment: number | null }) {
  if (sentiment === null) {
    return (
      <span className="font-sans font-bold text-[10.5px] tracking-wide px-2.5 py-1 rounded-full bg-[#191b1f] text-ink-faint">
        Neutral
      </span>
    );
  }
  const isPositive = sentiment > NEUTRAL_SENTIMENT_THRESHOLD;
  const isNegative = sentiment < -NEUTRAL_SENTIMENT_THRESHOLD;
  const label = isPositive ? "Positive" : isNegative ? "Negative" : "Neutral";
  const className = isPositive
    ? "bg-green text-hero-ink"
    : isNegative
      ? "bg-[#3a1f22] text-[#ff8a8a]"
      : "bg-[#191b1f] text-ink-faint";

  return (
    <span className={"font-sans font-bold text-[10.5px] tracking-wide px-2.5 py-1 rounded-full " + className}>
      {label}
    </span>
  );
}
