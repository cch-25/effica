import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return <section className="card card--padded" aria-busy="true"><Skeleton lines={6} /></section>;
}
