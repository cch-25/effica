import { PageHeader } from "@/components/layout/page-header";
import { serverApiRequest } from "@/lib/api/server";
import { isMockMode } from "@/lib/api/mode";
import { notFound } from "next/navigation";

type PublicShare = {
  id: string;
  template: string;
  display_name: string | null;
  snapshot: Record<string, unknown>;
  etag: string | null;
};

export default async function PublicSharePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const card = isMockMode()
    ? {
      id: "01H00000000000000000000006",
      template: "orbit",
      display_name: "김사이",
      snapshot: { x: 4, sensationalism: 18, confidence: 0.68 },
      etag: '"mock"',
    } satisfies PublicShare
    : await serverApiRequest<PublicShare>(`/public/share/${encodeURIComponent(token)}`).catch(() => null);
  if (!card) notFound();
  const snapshot = card.snapshot;
  const x = Number(snapshot.x ?? 0);
  const sensationalism = snapshot.sensationalism == null ? null : Number(snapshot.sensationalism);
  return (
    <>
      <PageHeader eyebrow="Public share" title={card.display_name || "관점 카드"} description="편향성과 과장성 점수의 공개 snapshot입니다." />
      <section className="card card--padded">
        <dl className="admin-item__meta" aria-label="공개 스냅샷">
          <div><dt>편향성</dt><dd>{x}</dd></div>
          <div><dt>과장성</dt><dd>{sensationalism == null ? "미측정" : sensationalism}</dd></div>
        </dl>
        <p><a className="button button--primary" href={`/api/v1/public/share/${encodeURIComponent(token)}/image`}>PNG 보기</a></p>
      </section>
    </>
  );
}
