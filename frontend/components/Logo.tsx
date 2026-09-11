// Header/navbar wordmark lockup — icon + "Stock Hyperion" text, side by side.
// Distinct from public/brand/master.svg, which is the square, opaque-background
// favicon/app-icon asset; this is a transparent inline mark meant to sit on
// whatever surface it's placed on (header, footer, login card, ...).
const ICON_PATH_SEGMENTS = [
  { line: [26, 36, 26, 78], rect: [20, 46, 12, 26], color: "#12E28A" },
  { line: [50, 18, 50, 78], rect: [44, 30, 12, 42], color: "#12E28A" },
  { line: [74, 8, 74, 78], rect: [68, 16, 12, 58], color: "#2F5BFF" },
] as const;

function LogoIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" fill="none" role="img" aria-hidden="true">
      {ICON_PATH_SEGMENTS.map((seg, i) => (
        <g key={i}>
          <line
            x1={seg.line[0]} y1={seg.line[1]} x2={seg.line[2]} y2={seg.line[3]}
            stroke={seg.color} strokeWidth={4.5} strokeLinecap="round"
          />
          <rect
            x={seg.rect[0]} y={seg.rect[1]} width={seg.rect[2]} height={seg.rect[3]}
            rx={6} fill={seg.color}
          />
        </g>
      ))}
    </svg>
  );
}

// One wordmark, everywhere — icon + "Stock Hyperion", no shortened variant.
export function Logo({
  iconSize = 28,
  textSize,
  theme = "dark",
  className = "",
}: {
  /** Icon diameter in px. */
  iconSize?: number;
  /** Wordmark font-size in px; defaults to a fixed ratio of iconSize. */
  textSize?: number;
  /** Which surface this sits on, so the wordmark stays legible on either. */
  theme?: "dark" | "light";
  className?: string;
}) {
  const textColor = theme === "dark" ? "#F4F5F6" : "#141413";
  const fontSize = textSize ?? Math.round(iconSize * 0.64);

  return (
    <span className={`logo-lockup inline-flex items-center gap-2 ${className}`} role="img" aria-label="Stock Hyperion">
      <span className="logo-icon-wrap inline-flex">
        <LogoIcon size={iconSize} />
      </span>
      <span
        style={{
          fontFamily: "var(--font-display)",
          color: textColor,
          letterSpacing: "-0.01em",
          fontSize: `${fontSize}px`,
          lineHeight: 1,
          whiteSpace: "nowrap",
        }}
      >
        Stock Hyperion
      </span>
    </span>
  );
}
