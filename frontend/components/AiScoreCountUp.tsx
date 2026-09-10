"use client";

import { useEffect, useState } from "react";

function easeOutQuad(t: number): number {
  return 1 - (1 - t) * (1 - t);
}

/** One-time entrance count-up (~700ms) when the hero score first mounts —
 * not a recurring/live effect. Instant (no animation) under
 * prefers-reduced-motion.
 *
 * No "already started" ref guard here — React Strict Mode (on by default
 * under `next dev`) double-invokes effects (mount -> cleanup -> mount) to
 * surface exactly this kind of bug: a guard ref survives the simulated
 * remount, so the second invocation saw it already `true`, returned early,
 * and the animation — cancelled by the first invocation's cleanup — never
 * restarted, permanently stuck at 0. The effect's own dependency array
 * already scopes re-runs correctly; nothing else needs to gate it.
 */
export function AiScoreCountUp({ value, durationMs = 700 }: { value: number; durationMs?: number }) {
  const target = Math.round(value);
  const [display, setDisplay] = useState(0);

  useEffect(() => {
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
