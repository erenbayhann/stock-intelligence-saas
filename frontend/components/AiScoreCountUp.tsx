"use client";

import { useEffect, useRef, useState } from "react";

function easeOutQuad(t: number): number {
  return 1 - (1 - t) * (1 - t);
}

/** One-time entrance count-up (~700ms) when the hero score first mounts —
 * not a recurring/live effect. Instant (no animation) under
 * prefers-reduced-motion. */
export function AiScoreCountUp({ value, durationMs = 700 }: { value: number; durationMs?: number }) {
  const target = Math.round(value);
  const [display, setDisplay] = useState(0);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    if (typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setDisplay(target);
      return;
    }

    let raf: number;
    const start = performance.now();
    const tick = (now: number) => {
      const elapsed = now - start;
      const progress = Math.min(elapsed / durationMs, 1);
      setDisplay(Math.round(target * easeOutQuad(progress)));
      if (progress < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, durationMs]);

  return <>{display}</>;
}
