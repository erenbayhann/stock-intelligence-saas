import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Equity Rankings",
  description:
    "Model-generated research signal for the S&P 100 universe. Not investment advice, not a guarantee of future returns.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Archivo+Black&family=Archivo:wght@500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-full flex flex-col">
        <header className="border-b border-panel-border">
          <div className="mx-auto max-w-6xl px-6 py-5 flex items-center justify-between">
            <Link href="/" className="font-display text-xl tracking-tight text-ink no-underline">
              AI EQUITY RANKINGS
            </Link>
            <nav className="font-mono-tabular text-xs text-ink-faint flex items-center gap-5">
              <Link href="/" className="hover:text-ink-soft no-underline">
                Rankings
              </Link>
              <Link href="/methodology" className="hover:text-ink-soft no-underline">
                Methodology
              </Link>
              <Link href="/admin" className="hover:text-ink-soft no-underline">
                Admin
              </Link>
            </nav>
          </div>
        </header>
        <main className="flex-1 mx-auto w-full max-w-6xl px-6 py-8">{children}</main>
        <footer className="border-t border-panel-border">
          <div className="mx-auto max-w-6xl px-6 py-5 text-xs text-ink-soft">
            Research and decision-support tool only. Model-generated research
            signal, not investment advice. Not a guarantee of future returns.{" "}
            <Link href="/methodology" className="underline hover:text-ink">
              Methodology &amp; limitations.
            </Link>
          </div>
        </footer>
      </body>
    </html>
  );
}
