"use client";

import { useState } from "react";
import type { NewsHistoryDay, TopNewsItem } from "@/lib/api";
import { formatLongDate } from "@/lib/format";
import { NewsList } from "@/components/NewsList";

type Tab = "today" | "history";

export function NewsTabs({ today, history }: { today: TopNewsItem[]; history: NewsHistoryDay[] }) {
  const [tab, setTab] = useState<Tab>("today");

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <button
          onClick={() => setTab("today")}
          className={
            "font-mono-tabular text-xs px-3.5 py-1.5 rounded-full border " +
            (tab === "today" ? "bg-green text-hero-ink border-green" : "text-ink-faint border-panel-border")
          }
        >
          Today
        </button>
        <button
          onClick={() => setTab("history")}
          className={
            "font-mono-tabular text-xs px-3.5 py-1.5 rounded-full border " +
            (tab === "history" ? "bg-green text-hero-ink border-green" : "text-ink-faint border-panel-border")
          }
        >
          Last 7 Days
        </button>
      </div>

      {tab === "today" ? (
        <NewsList items={today} emptyMessage="No classified news in the last 48 hours yet." />
      ) : history.length === 0 ? (
        <div className="rounded-2xl border border-panel-border bg-panel px-5 py-6 text-sm text-ink-soft">
          No classified news in the last 7 days yet.
        </div>
      ) : (
        <div className="space-y-6">
          {history.map((day) => (
            <div key={day.date}>
              <div className="text-[10.5px] font-bold uppercase tracking-widest text-ink-soft mb-3">
                {formatLongDate(day.date)}
              </div>
              <NewsList items={day.items} emptyMessage="No classified news that day." />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
