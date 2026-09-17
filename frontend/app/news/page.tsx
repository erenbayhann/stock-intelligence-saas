import Link from "next/link";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { SentimentBadge } from "@/components/SentimentBadge";

export const metadata = {
  title: "News",
};

export default async function NewsPage() {
  const news = await api.topNews(30);
  const items = news?.items ?? [];

  return (
    <div>
      <div className="font-display text-[22px] tracking-tight text-ink mb-3">
        TODAY&apos;S NEWS SIGNALS
      </div>
      <div className="text-[10.5px] font-bold uppercase tracking-widest text-ink-soft mb-4">
        Ranked by the model&apos;s own relevance &amp; importance scoring
      </div>

      <div className="flex items-center gap-2.5 rounded-xl border border-panel-border bg-[#0c0d0e] px-5 py-3.5 mb-6 text-xs text-ink-soft">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#9195A0" strokeWidth="2">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 8v5M12 16h.01" />
        </svg>
        This is a same-day news digest, not a prediction — it is independent
        of the AI Score ranking model and is not investment advice.{" "}
        <Link href="/methodology" className="text-ink-soft underline hover:text-ink">
          See Methodology.
        </Link>
      </div>

      <div className="rounded-2xl border border-panel-border bg-panel overflow-hidden">
        {items.length === 0 ? (
          <div className="px-5 py-6 text-sm text-ink-soft">
            No classified news in the last 48 hours yet.
          </div>
        ) : (
          items.map((item, i) => (
            <div
              key={`${item.ticker}-${item.url}`}
              className="px-5 py-4 border-b border-row-border last:border-b-0"
            >
              <div className="flex items-center justify-between gap-3 mb-1.5">
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
          ))
        )}
      </div>
    </div>
  );
}
