import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { Logo } from "@/components/Logo";
import "./globals.css";

const SITE_NAME = "Stock Hyperion";
const SITE_DESCRIPTION =
  "Stock Hyperion — AI-powered equity rankings for the S&P 100. Model-generated research signal, not investment advice, not a guarantee of future returns.";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
  title: { default: SITE_NAME, template: `%s · ${SITE_NAME}` },
  description: SITE_DESCRIPTION,
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/favicon-32x32.png", sizes: "32x32", type: "image/png" },
      { url: "/favicon-16x16.png", sizes: "16x16", type: "image/png" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
  manifest: "/site.webmanifest",
  openGraph: {
    title: SITE_NAME,
    description: SITE_DESCRIPTION,
    siteName: SITE_NAME,
    images: [{ url: "/android-chrome-512x512.png", width: 512, height: 512 }],
    type: "website",
  },
  twitter: {
    card: "summary",
    title: SITE_NAME,
    description: SITE_DESCRIPTION,
    images: ["/android-chrome-512x512.png"],
  },
};

export const viewport: Viewport = {
  themeColor: "#111214",
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
            <Link href="/" className="no-underline">
              <Logo />
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
          <div className="mx-auto max-w-6xl px-6 py-5 flex flex-col sm:flex-row sm:items-center gap-3 text-xs text-ink-soft">
            <Logo iconSize={18} textSize={13} />
            <div>
              Research and decision-support tool only. Model-generated research
              signal, not investment advice. Not a guarantee of future returns.{" "}
              <Link href="/methodology" className="underline hover:text-ink">
                Methodology &amp; limitations.
              </Link>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
