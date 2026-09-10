import { Skeleton } from "@/components/Skeleton";

export default function DayDetailLoading() {
  return (
    <div>
      <Skeleton className="h-3 w-24 mb-4" />
      <Skeleton className="h-8 w-64 mb-2" />
      <Skeleton className="h-3 w-72 mb-6" />

      <div className="grid grid-cols-[1fr_220px_220px] gap-3.5 mb-6">
        <Skeleton className="h-24 rounded-2xl" />
        <Skeleton className="h-24 rounded-2xl" />
        <Skeleton className="h-24 rounded-2xl" />
      </div>

      <div className="rounded-2xl border border-panel-border bg-panel mb-4 overflow-hidden">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="px-5 py-3.5 border-b border-row-border last:border-b-0 flex items-center gap-4">
            <Skeleton className="h-4 w-6" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-20" />
              <Skeleton className="h-3 w-32" />
            </div>
            <Skeleton className="h-6 w-14" />
          </div>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-3.5">
        <Skeleton className="h-24 rounded-2xl" />
        <Skeleton className="h-24 rounded-2xl" />
        <Skeleton className="h-24 rounded-2xl" />
      </div>
    </div>
  );
}
