import { Skeleton } from "@/components/Skeleton";

export default function DashboardLoading() {
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <Skeleton className="h-3 w-40" />
        <Skeleton className="h-3 w-56" />
      </div>

      <div className="rounded-2xl border border-panel-border bg-panel mb-4 overflow-hidden">
        <div className="px-5 py-3 border-b border-panel-border">
          <Skeleton className="h-3 w-full" />
        </div>
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="px-5 py-4 border-b border-row-border last:border-b-0 flex items-center gap-4">
            <Skeleton className="h-4 w-6" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-3 w-40" />
            </div>
            <Skeleton className="h-6 w-14" />
            <Skeleton className="h-6 w-16 rounded-full" />
          </div>
        ))}
      </div>

      <div className="grid grid-cols-[380px_1fr] gap-4 mb-4">
        <Skeleton className="h-[220px] rounded-2xl" />
        <Skeleton className="h-[220px] rounded-2xl" />
      </div>

      <Skeleton className="h-12 rounded-xl mb-6" />

      <Skeleton className="h-3 w-28 mb-3" />
      <Skeleton className="h-40 rounded-2xl mb-4" />

      <div className="grid grid-cols-3 gap-3.5">
        <Skeleton className="h-24 rounded-2xl" />
        <Skeleton className="h-24 rounded-2xl" />
        <Skeleton className="h-24 rounded-2xl" />
      </div>
    </div>
  );
}
