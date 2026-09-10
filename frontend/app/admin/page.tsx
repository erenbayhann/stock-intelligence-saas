"use client";

import { useCallback, useEffect, useState } from "react";
import { PUBLIC_API_BASE } from "@/lib/api";
import { Skeleton } from "@/components/Skeleton";

interface JobHealthItem {
  job_name: string;
  status: string;
  started_at: string;
  finished_at: string | null;
}

interface AlertItem {
  id: number;
  severity: string;
  category: string;
  message: string;
  created_at: string;
  acknowledged_at: string | null;
}

interface ChallengerItem {
  id: number;
  version_label: string;
  algorithm: string;
  feature_set: string;
  trained_at: string;
  metrics: { test?: Record<string, number> };
}

interface ChallengersPending {
  champion_metrics: Record<string, unknown> | null;
  challengers: ChallengerItem[];
}

interface CreditStatus {
  estimated_remaining_usd: number;
  total_topped_up_usd: number;
  total_spent_usd: number;
  trailing_daily_burn_usd: number | null;
  estimated_days_until_depleted: number | null;
  low_balance_warning: boolean;
}

interface NewsRolloutProgress {
  eligible: boolean;
  trading_days_covered: number;
  trading_days_required: number;
  window_size: number;
  coverage_pct: number;
  estimated_eligible_date: string | null;
}

async function adminFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${PUBLIC_API_BASE}${path}`, {
    credentials: "include",
    ...init,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

type AuthState = "checking" | "authed" | "anon";

export default function AdminPage() {
  const [authed, setAuthed] = useState<AuthState>("checking");
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [jobs, setJobs] = useState<JobHealthItem[]>([]);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [challengers, setChallengers] = useState<ChallengersPending | null>(null);
  const [credit, setCredit] = useState<CreditStatus | null>(null);
  const [newsRollout, setNewsRollout] = useState<NewsRolloutProgress | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const loadDashboard = useCallback(async () => {
    try {
      const [jobsRes, alertsRes, challengersRes, creditRes, rolloutRes] = await Promise.all([
        adminFetch<{ jobs: JobHealthItem[] }>("/api/v1/admin/jobs"),
        adminFetch<{ alerts: AlertItem[] }>("/api/v1/admin/alerts?unacknowledged_only=true"),
        adminFetch<ChallengersPending>("/api/v1/admin/challengers/pending"),
        adminFetch<CreditStatus>("/api/v1/admin/credit-status"),
        adminFetch<NewsRolloutProgress>("/api/v1/admin/news-rollout-progress"),
      ]);
      setJobs(jobsRes.jobs);
      setAlerts(alertsRes.alerts);
      setChallengers(challengersRes);
      setCredit(creditRes);
      setNewsRollout(rolloutRes);
      setAuthed("authed");
    } catch {
      setAuthed("anon");
    }
  }, []);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setLoginError(null);
    try {
      await adminFetch("/api/v1/admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      await loadDashboard();
    } catch (err) {
      setLoginError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleApprove(id: number) {
    setActionError(null);
    try {
      await adminFetch(`/api/v1/admin/challengers/${id}/approve`, { method: "POST" });
      await loadDashboard();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Approve failed");
    }
  }

  async function handleReject(id: number) {
    setActionError(null);
    try {
      await adminFetch(`/api/v1/admin/challengers/${id}/reject`, { method: "POST" });
      await loadDashboard();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Reject failed");
    }
  }

  async function handleAcknowledge(id: number) {
    setActionError(null);
    try {
      await adminFetch(`/api/v1/admin/alerts/${id}/acknowledge`, { method: "POST" });
      await loadDashboard();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Acknowledge failed");
    }
  }

  if (authed === "checking") {
    return (
      <div className="max-w-sm mx-auto mt-16">
        <Skeleton className="h-3 w-20 mx-auto mb-4" />
        <Skeleton className="h-40 rounded-2xl" />
      </div>
    );
  }

  if (authed === "anon") {
    return (
      <div className="max-w-sm mx-auto mt-16">
        <div className="text-[10.5px] font-bold uppercase tracking-widest text-ink-soft mb-4 text-center">
          Admin
        </div>
        <form onSubmit={handleLogin} className="rounded-2xl border border-panel-border bg-panel p-6">
          <label className="block text-xs text-ink-soft mb-2">Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-lg bg-[#0c0d0e] border border-panel-border px-3 py-2 text-ink font-mono-tabular text-sm mb-3 outline-none focus:border-green"
            autoFocus
          />
          {loginError && <div className="text-xs text-negative mb-3">{loginError}</div>}
          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-full bg-green text-hero-ink font-bold text-sm py-2 disabled:opacity-50"
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="text-[10.5px] font-bold uppercase tracking-widest text-ink-soft">
        Admin &middot; operational status
      </div>
      {actionError && (
        <div className="rounded-xl border border-negative/40 bg-negative/10 px-4 py-3 text-sm text-negative">
          {actionError}
        </div>
      )}

      <section>
        <h2 className="font-sans font-bold text-sm mb-3">Job health</h2>
        <div className="rounded-2xl border border-panel-border bg-panel overflow-hidden">
          {jobs.map((job) => (
            <div
              key={job.job_name}
              className="grid grid-cols-[1fr_100px_180px] items-center px-5 py-3 border-b border-row-border last:border-b-0 text-sm row-hover"
            >
              <div className="text-ink-news">{job.job_name}</div>
              <div
                className={
                  "font-mono-tabular text-xs " +
                  (job.status === "success" ? "text-green" : job.status === "failed" ? "text-negative" : "text-ink-faint")
                }
              >
                {job.status}
              </div>
              <div className="font-mono-tabular text-xs text-ink-faint">
                {new Date(job.started_at).toLocaleString()}
              </div>
            </div>
          ))}
          {jobs.length === 0 && <div className="px-5 py-4 text-sm text-ink-soft">No job runs yet.</div>}
        </div>
      </section>

      <section>
        <h2 className="font-sans font-bold text-sm mb-3">Unacknowledged data-quality alerts</h2>
        <div className="rounded-2xl border border-panel-border bg-panel overflow-hidden">
          {alerts.map((alert) => (
            <div
              key={alert.id}
              className="flex items-center justify-between gap-4 px-5 py-3 border-b border-row-border last:border-b-0 text-sm"
            >
              <div>
                <span
                  className={
                    "font-mono-tabular text-xs mr-2 " +
                    (alert.severity === "error"
                      ? "text-negative"
                      : alert.severity === "warning"
                        ? "text-blue"
                        : "text-ink-faint")
                  }
                >
                  {alert.severity}
                </span>
                <span className="text-ink-news">{alert.message}</span>
              </div>
              <button
                onClick={() => handleAcknowledge(alert.id)}
                className="font-mono-tabular text-xs text-ink-faint border border-panel-border rounded-full px-3 py-1 hover:text-ink-soft"
              >
                Acknowledge
              </button>
            </div>
          ))}
          {alerts.length === 0 && <div className="px-5 py-4 text-sm text-ink-soft">No open alerts.</div>}
        </div>
      </section>

      <section>
        <h2 className="font-sans font-bold text-sm mb-3">Pending challengers</h2>
        <div className="rounded-2xl border border-panel-border bg-panel overflow-hidden">
          {challengers?.challengers.map((c) => (
            <div key={c.id} className="px-5 py-4 border-b border-row-border last:border-b-0">
              <div className="flex items-center justify-between mb-1.5">
                <div className="font-display text-sm">{c.version_label}</div>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleApprove(c.id)}
                    className="font-mono-tabular text-xs bg-green text-hero-ink rounded-full px-3 py-1"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => handleReject(c.id)}
                    className="font-mono-tabular text-xs text-negative border border-negative/40 rounded-full px-3 py-1"
                  >
                    Reject
                  </button>
                </div>
              </div>
              <div className="font-mono-tabular text-xs text-ink-faint">
                {c.algorithm} &middot; test rank IC{" "}
                {c.metrics.test?.mean_rank_ic !== undefined ? c.metrics.test.mean_rank_ic.toFixed(4) : "—"}
                {" · "}precision@5{" "}
                {c.metrics.test?.precision_at_5 !== undefined
                  ? `${Math.round(c.metrics.test.precision_at_5 * 100)}%`
                  : "—"}
              </div>
            </div>
          ))}
          {(!challengers || challengers.challengers.length === 0) && (
            <div className="px-5 py-4 text-sm text-ink-soft">No pending challengers.</div>
          )}
        </div>
      </section>

      <section className="grid grid-cols-2 gap-4">
        <div className="rounded-2xl border border-panel-border bg-panel p-5">
          <h2 className="font-sans font-bold text-sm mb-3">LLM / API credit balance</h2>
          {credit ? (
            <div className="space-y-1.5 text-sm">
              <div className="flex justify-between">
                <span className="text-ink-soft">Estimated remaining</span>
                <span className="font-mono-tabular">${credit.estimated_remaining_usd.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-ink-soft">Total spent</span>
                <span className="font-mono-tabular">${credit.total_spent_usd.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-ink-soft">Days until depleted</span>
                <span className="font-mono-tabular">
                  {credit.estimated_days_until_depleted?.toFixed(0) ?? "—"}
                </span>
              </div>
              {credit.low_balance_warning && (
                <div className="text-negative text-xs mt-2">Low balance warning active.</div>
              )}
            </div>
          ) : (
            <div className="text-sm text-ink-soft">Unavailable</div>
          )}
        </div>

        <div className="rounded-2xl border border-panel-border bg-panel p-5">
          <h2 className="font-sans font-bold text-sm mb-3">News coverage rollout</h2>
          {newsRollout ? (
            <div className="space-y-1.5 text-sm">
              <div className="flex justify-between">
                <span className="text-ink-soft">Eligible for full display</span>
                <span className={newsRollout.eligible ? "text-green" : "text-ink-faint"}>
                  {newsRollout.eligible ? "Yes" : "Not yet"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-ink-soft">Trading days covered</span>
                <span className="font-mono-tabular">
                  {newsRollout.trading_days_covered}/{newsRollout.window_size}
                </span>
              </div>
              {!newsRollout.eligible && newsRollout.estimated_eligible_date && (
                <div className="text-xs text-ink-faint mt-2">
                  Estimated eligible: {newsRollout.estimated_eligible_date}
                </div>
              )}
            </div>
          ) : (
            <div className="text-sm text-ink-soft">Unavailable</div>
          )}
        </div>
      </section>
    </div>
  );
}
