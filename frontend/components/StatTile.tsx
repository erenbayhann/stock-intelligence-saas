const VARIANT_CLASSES: Record<"green" | "blue" | "white", string> = {
  green: "bg-gradient-to-br from-green-grad-from to-green-grad-to text-hero-ink",
  blue: "bg-blue text-blue-ink",
  white: "bg-white-card text-white-card-ink",
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
    <div className={`rounded-2xl px-5 py-5 ${VARIANT_CLASSES[variant]}`}>
      <div className="font-display text-[34px] leading-none">{value}</div>
      <div className="font-sans font-bold text-[10.5px] uppercase tracking-wide mt-2 opacity-75">
        {label}
      </div>
    </div>
  );
}
