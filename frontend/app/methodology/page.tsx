import Link from "next/link";
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Methodology & Limitations",
  description:
    "How Stock Hyperion's daily S&P 100 ranking actually works — data sources, update cadence, and known limitations.",
};

function FlowIcon({ children }: { children: ReactNode }) {
  return (
    <div className="w-9 h-9 rounded-full bg-[#191b1f] border border-[#2a2d33] flex items-center justify-center text-green flex-none">
      {children}
    </div>
  );
}

function FlowArrow() {
  return (
    <svg width="20" height="14" viewBox="0 0 24 14" fill="none" stroke="#3a3d45" strokeWidth="2" className="flex-none hidden md:block">
      <path d="M1 7h20M15 1l6 6-6 6" />
    </svg>
  );
}

function FlowStep({ icon, title, note }: { icon: ReactNode; title: string; note: string }) {
  return (
    <div className="flex items-start gap-3 flex-1 min-w-[140px]">
      <FlowIcon>{icon}</FlowIcon>
      <div>
        <div className="text-sm font-bold text-ink">{title}</div>
        <div className="text-xs text-ink-soft mt-0.5 leading-relaxed">{note}</div>
      </div>
    </div>
  );
}

function Card({ title, children, badge }: { title: string; children: ReactNode; badge?: ReactNode }) {
  return (
    <section className="rounded-2xl border border-panel-border bg-panel p-6 mb-4 hover-lift hover-glow-neutral">
      <div className="flex items-center gap-2.5 mb-3.5">
        {badge}
        <h2 className="font-sans font-bold text-[15px] m-0">{title}</h2>
      </div>
      <div className="text-sm text-ink-news leading-relaxed space-y-3">{children}</div>
    </section>
  );
}

export default function MethodologyPage() {
  return (
    <div className="max-w-3xl">
      <Link
        href="/"
        className="flex items-center gap-1.5 font-mono-tabular text-xs text-ink-faint no-underline mb-6 w-fit hover:text-ink-soft"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
          <path d="M15 18l-6-6 6-6" />
        </svg>
        Rankings
      </Link>

      <div className="text-[10.5px] font-bold uppercase tracking-widest text-ink-soft mb-2">
        Methodology &amp; Limitations
      </div>
      <h1 className="font-display text-3xl mb-2">How this ranking works</h1>
      <p className="text-sm text-ink-soft leading-relaxed mb-8 max-w-xl">
        A plain-language walkthrough of what Stock Hyperion actually is, where its data comes
        from, how often it updates, and what it honestly can&rsquo;t do yet.
      </p>

      <div className="rounded-2xl border border-panel-border bg-panel p-6 mb-8">
        <div className="text-[10.5px] font-bold uppercase tracking-widest text-ink-soft mb-4">
          The daily cycle
        </div>
        <div className="flex flex-col md:flex-row items-start md:items-center gap-4 md:gap-3">
          <FlowStep
            title="Data"
            note="Prices, filings, macro series, and news collected overnight."
            icon={
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M4 19V9M10 19V5M16 19v-7M22 19H2" />
              </svg>
            }
          />
          <FlowArrow />
          <FlowStep
            title="Model"
            note="A trained ranking model scores all 100 stocks before the open."
            icon={
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="6" y="6" width="12" height="12" rx="2" /><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4" />
              </svg>
            }
          />
          <FlowArrow />
          <FlowStep
            title="Top 5"
            note="Only the five highest-scored picks are ever surfaced, locked at ~09:15 ET."
            icon={
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
              </svg>
            }
          />
          <FlowArrow />
          <FlowStep
            title="Outcome"
            note="After the session closes, the real result is recorded — always, win or lose."
            icon={
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><path d="M22 4L12 14.01l-3-3" />
              </svg>
            }
          />
        </div>
      </div>

      <Card
        title="What this is"
        badge={
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#12E28A" strokeWidth="2"><circle cx="12" cy="12" r="9" /><path d="M12 16v-5M12 8h.01" /></svg>
        }
      >
        <p>
          A research and decision-support tool for the S&amp;P 100 universe. It is <strong>not a
          trading bot</strong>, does not execute trades, and never gives personalized investment
          advice. Rankings are a model-generated research signal, not a guarantee of future
          returns.
        </p>
      </Card>

      <Card
        title="How often data updates"
        badge={
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#2F5BFF" strokeWidth="2"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></svg>
        }
      >
        <p>
          Market prices are <strong>daily bars</strong>, refreshed once per day after the regular
          session closes (~16:20 ET) — not tick-level or continuously streamed. The price chart on
          each stock&rsquo;s page shows the timestamp of the most recent bar it has; treat that
          timestamp as the data&rsquo;s actual freshness, not &ldquo;now.&rdquo;
        </p>
        <p>
          News is gathered at regular intervals overnight, not polled continuously. A
          fast-breaking story between two of those sweeps won&rsquo;t appear until the next one
          runs.
        </p>
        <p>
          Exactly one prediction is generated and locked per trading day, shortly before the
          09:30 ET open, using only data available by that moment. There is no intraday
          re-prediction — the top 5 for a given session doesn&rsquo;t change after it&rsquo;s
          locked.
        </p>
      </Card>

      <Card
        title="Data sources"
        badge={
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#12E28A" strokeWidth="2"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zM2 12h20M12 2a15 15 0 0 1 0 20 15 15 0 0 1 0-20z" /></svg>
        }
      >
        <p>
          Up-to-date market data, company filings, macroeconomic indicators, and news sources feed
          every day&rsquo;s ranking.
        </p>
        <p className="text-xs text-ink-soft">
          Macro data uses point-in-time vintages, so a later revision (e.g. a GDP update) never
          leaks backward into a prediction made before that revision existed.
        </p>
      </Card>

      <Card
        title="Known limitations"
        badge={
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#FF6B5E" strokeWidth="2"><path d="M12 9v4M12 17h.01M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /></svg>
        }
      >
        <ul className="list-disc pl-5 space-y-2">
          <li>
            News coverage depth is still growing; early history has sparser coverage than recent
            days.
          </li>
          <li>
            Predictions and their outcomes are never deleted or cherry-picked, including incorrect
            ones — the &ldquo;Last 7 Days&rdquo; view always reflects the full, real record.
          </li>
          <li>
            Model performance shown throughout this product (hit rate, directional accuracy, etc.)
            is measured out of sample on real predictions, not a backtest presented as if it were
            live performance — but past performance, real or backtested, still does not guarantee
            future results.
          </li>
        </ul>
      </Card>

      <Card
        title="Champion / challenger models"
        badge={
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#2F5BFF" strokeWidth="2"><path d="M4 21V9m8 12V3m8 18v-6" /></svg>
        }
      >
        <p>
          The model making live predictions (the &ldquo;champion&rdquo;) is retrained periodically
          alongside experimental &ldquo;challenger&rdquo; models. A challenger only ever replaces
          the champion after a human reviews its measured performance — nothing is promoted
          automatically.
        </p>
      </Card>

      <div className="flex items-center gap-2.5 rounded-xl border border-panel-border bg-[#0c0d0e] px-5 py-3.5 mt-8 text-xs text-ink-soft">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#9195A0" strokeWidth="2" className="flex-none">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 8v5M12 16h.01" />
        </svg>
        This page describes a research and decision-support tool. Nothing here is investment
        advice, and nothing on this site guarantees future returns.
      </div>
    </div>
  );
}
