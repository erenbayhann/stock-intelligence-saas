"use client";

import { useState } from "react";
import type { NewsPickRun } from "@/lib/api";
import { formatDateTimeEt, formatLongDate, formatPercent } from "@/lib/format";
import { NewsPickList } from "@/components/NewsPickCard";

type Tab = "latest" | "history";

const EMPTY_RUN = "No stock had net-positive news before this session's lock, so nothing was picked.";

function RunHeader({ run }: { run: NewsPickRun }) {
  return (
    <div className="mb-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <div className="font-display text-lg text-ink">{formatLongDate(run.target_session_date)}</div>
        {run.reconstructed && (
          <span
            title="Written after the fact from only the headlines that were already classified before this session's 09:15 AM ET lock."
            className="font-mono-tabular text-[10px] uppercase tracking-wide text-ink-soft border border-panel-border rounded-full px-2.5 py-0.5"
          >
            Reconstructed
          </span>
        )}
      </div>
      <div className="font-mono-tabular text-[11px] text-ink-faint mt-1">
        Cutoff {formatDateTimeEt(run.as_of)} &middot; headlines since {formatDateTimeEt(run.window_start)} &middot;{" "}
        {run.candidates_scored} stock{run.candidates_scored === 1 ? "" : "s"} with news scored
      </div>
      {run.hit_rate !== null && (
        <div className="font-mono-tabular text-[11px] text-ink-soft mt-1">
          {Math.round(run.hit_rate * 100)}% beat the S&amp;P 500
          {run.benchmark_return !== null && <> &middot; S&amp;P 500 {formatPercent(run.benchmark_return)} that session</>}
        </div>
      )}
    </div>
  );
}

export function NewsPicksTabs({ latest, history }: { latest: NewsPickRun | null; history: NewsPickRun[] }) {
  const [tab, setTab] = useState<Tab>("latest");

  const tabClass = (active: boolean) =>
    "font-mono-tabular text-xs px-3.5 py-1.5 rounded-full border " +
    (active ? "bg-green text-hero-ink border-green" : "text-ink-faint border-panel-border");

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <button onClick={() => setTab("latest")} className={tabClass(tab === "latest")}>
          Latest Picks
        </button>
        <button onClick={() => setTab("history")} className={tabClass(tab === "history")}>
          Last 7 Days
        </button>
      </div>

      {tab === "latest" ? (
        latest ? (
          <>
            <RunHeader run={latest} />
            <NewsPickList picks={latest.picks} emptyMessage={EMPTY_RUN} />
          </>
        ) : (
          <div className="rounded-2xl border border-panel-border bg-panel px-5 py-6 text-sm text-ink-soft">
            No news picks have been locked yet. The first set locks at 09:15 AM ET on the next trading day, from
            the headlines classified since the previous close.
          </div>
        )
      ) : history.length === 0 ? (
        <div className="rounded-2xl border border-panel-border bg-panel px-5 py-6 text-sm text-ink-soft">
          No past sessions yet.
        </div>
      ) : (
        <div className="space-y-8">
          {history.map((run) => (
            <div key={run.target_session_date}>
              <RunHeader run={run} />
              <NewsPickList picks={run.picks} emptyMessage={EMPTY_RUN} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
