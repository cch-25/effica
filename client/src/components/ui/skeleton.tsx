export function Skeleton({ lines = 3 }: { lines?: number }) {
  return <div className="skeleton" role="status"><span className="sr-only">불러오는 중</span>{Array.from({ length: lines }, (_, index) => <span key={index} aria-hidden="true" />)}</div>;
}
