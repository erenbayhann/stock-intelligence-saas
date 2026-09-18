import Link from "next/link";
import type { TopNewsItem } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { SentimentBadge } from "@/components/SentimentBadge";

export function NewsList({ items, emptyMessage }: { items: TopNewsItem[]; emptyMessage: string }) {
  if (items.length === 0) {
    return (
      <div className="rounded-2xl border border-panel-border bg-panel px-5 py-6 text-sm text-ink-soft">
        {emptyMessage}
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-panel-border bg-panel overflow-hidden">
      {items.map((item, i) => (
        <div
          key={`${item.ticker}-${item.url}`}
          className="px-5 py-4 max-md:px-4 border-b border-row-border last:border-b-0"
        >
          <div className="flex items-center justify-between gap-3 max-md:flex-wrap max-md:gap-1.5 mb-1.5">
            <div className="flex items-center gap-2.5">
              <span className="font-mono-tabular text-xs text-ink-dim">
                {String(i + 1).padStart(2, "0")}
              </span>
              <Link href={`/stocks/${item.ticker}`} className="font-display text-sm text-ink no-underline hover:text-ink-soft">
                {item.ticker}
              </Link>
              <span className="text-xs text-ink-soft">{item.company_name}</span>
            </div>
            <SentimentBadge sentiment={item.sentiment} />
          </div>
          <a
            href={item.url}
            target="_blank"
            rel="noreferrer"
            className="text-sm text-ink-news hover:text-ink"
          >
            {item.title}
          </a>
          <div className="flex items-center gap-2 mt-2">
            {item.event_category && (
              <span className="text-[11px] font-semibold text-ink bg-[#191b1f] border border-[#2a2d33] rounded-full px-3 py-1">
                {item.event_category}
              </span>
            )}
            <span className="font-mono-tabular text-[11px] text-ink-faint">
              {item.source} &middot; {timeAgo(item.published_time)}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
