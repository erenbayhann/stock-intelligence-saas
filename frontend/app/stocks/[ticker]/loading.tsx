import { Skeleton } from "@/components/Skeleton";

export default function StockDetailLoading() {
  return (
    <div>
      <Skeleton className="h-3 w-20 mb-5" />
      <Skeleton className="h-10 w-32 mb-2" />
      <Skeleton className="h-3 w-48 mb-6" />

      <div className="grid grid-cols-[1fr_320px] gap-4 my-5">
        <Skeleton className="h-[280px] rounded-2xl" />
        <Skeleton className="h-[280px] rounded-2xl" />
      </div>

      <div className="grid grid-cols-6 gap-3 mb-5">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-16 rounded-2xl" />
        ))}
      </div>

      <Skeleton className="h-3 w-28 mb-3" />
      <Skeleton className="h-32 rounded-2xl mb-6" />
      <Skeleton className="h-3 w-40 mb-3" />
      <Skeleton className="h-48 rounded-2xl" />
    </div>
  );
}
