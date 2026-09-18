import Link from "next/link";
import { api } from "@/lib/api";
import { NewsTabs } from "@/components/NewsTabs";

export const metadata = {
  title: "News",
};

export default async function NewsPage() {
  const [news, history] = await Promise.all([api.topNews(5), api.newsHistory(7)]);

  return (
    <div>
      <div className="font-display text-[22px] tracking-tight text-ink mb-3">
        TOP 5 NEWS SIGNALS
      </div>
      <div className="text-[10.5px] font-bold uppercase tracking-widest text-ink-soft mb-4">
        Today&apos;s highest relevance &amp; importance scored headlines
      </div>

      <div className="flex items-center gap-2.5 rounded-xl border border-panel-border bg-[#0c0d0e] px-5 py-3.5 mb-6 text-xs text-ink-soft">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#9195A0" strokeWidth="2">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 8v5M12 16h.01" />
        </svg>
        This is a news digest, not a prediction — it is independent of the AI
        Score ranking model and is not investment advice.{" "}
        <Link href="/methodology" className="text-ink-soft underline hover:text-ink">
          See Methodology.
        </Link>
      </div>

      <NewsTabs today={news?.items ?? []} history={history?.days ?? []} />
    </div>
  );
}
