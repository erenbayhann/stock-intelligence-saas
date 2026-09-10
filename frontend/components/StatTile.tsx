const VARIANT_CLASSES: Record<"green" | "blue" | "white", string> = {
  green: "bg-gradient-to-br from-green-grad-from to-green-grad-to text-hero-ink tile-green",
  blue: "bg-blue text-blue-ink tile-blue",
  white: "bg-white-card text-white-card-ink tile-white",
};

export function StatTile({
  value,
  label,
  variant,
}: {
  value: string;
  label: string;
  variant: "green" | "blue" | "white";
}) {
  return (
    <div className={`rounded-2xl px-5 py-5 stat-tile-interactive ${VARIANT_CLASSES[variant]}`}>
      <div className="font-display text-[34px] leading-none relative z-[1]">{value}</div>
      <div className="font-sans font-bold text-[10.5px] uppercase tracking-wide mt-2 opacity-75 relative z-[1]">
        {label}
      </div>
    </div>
  );
}
