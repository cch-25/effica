export function Skeleton({ lines = 3 }: { lines?: number }) {
  return <div className="skeleton" aria-label="불러오는 중">{Array.from({ length: lines }, (_, index) => <span key={index} />)}</div>;
}
