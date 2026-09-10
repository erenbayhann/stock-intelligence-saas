export function ConfidencePill({ confidence }: { confidence: string }) {
  const isHigh = confidence.toLowerCase() === "high";
  return (
    <span
      className={
        "font-sans font-bold text-[10.5px] tracking-wide px-2.5 py-1 rounded-full " +
        (isHigh ? "bg-green text-hero-ink" : "bg-blue text-blue-ink")
      }
    >
      {confidence}
    </span>
  );
}
