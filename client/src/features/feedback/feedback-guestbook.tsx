"use client";

import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUpRight, Check, LoaderCircle } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { apiRequest } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";

type FeedbackPage = components["schemas"]["FeedbackPage"];
type FeedbackView = components["schemas"]["FeedbackView"];
const queryKey = ["feedback"] as const;
const dateFormat = new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit", timeZone: "Asia/Seoul" });

export function FeedbackGuestbook() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [posted, setPosted] = useState<FeedbackView | null>(null);
  const submission = useRef<{ key: string; signature: string } | null>(null);
  const submitting = useRef(false);
  const count = Array.from(content).length;
  const overLimit = count > 200;
  const feedback = useInfiniteQuery({
    queryKey,
    initialPageParam: "",
    queryFn: ({ pageParam }) => apiRequest<FeedbackPage>(`/feedback${pageParam ? `?cursor=${encodeURIComponent(pageParam)}` : ""}`, { cache: "no-store" }),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });
  const entries = feedback.data?.pages.flatMap((page) => page.items) ?? [];
  const visibleEntries = posted && !entries.some((entry) => entry.id === posted.id) ? [posted, ...entries] : entries;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || overLimit || !name.trim() || !content.trim()) return;
    submitting.current = true;
    setPending(true);
    setError("");
    const signature = JSON.stringify([name.trim(), content.trim()]);
    if (submission.current?.signature !== signature) submission.current = { key: crypto.randomUUID(), signature };
    try {
      const entry = await apiRequest<FeedbackView>("/feedback", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), content: content.trim(), submission_key: submission.current.key }),
        authFailureMode: "return-error",
      });
      setPosted(entry);
      setContent("");
      submission.current = null;
      void queryClient.invalidateQueries({ queryKey });
    } catch {
      setError("등록하지 못했어요. 작성한 내용은 그대로 있으니 다시 시도해 주세요.");
    } finally {
      submitting.current = false;
      setPending(false);
    }
  }

  return <div className="feedback-page">
    <header className="feedback-heading">
      <div><p className="feedback-kicker">독자 방명록</p><h1>피드백</h1><p>에피카를 읽고 느낀 점을 자유롭게 남겨 주세요.</p></div>
      <span className="feedback-heading__note">여러분의 한마디를<br />다음 지면에 담겠습니다.</span>
    </header>
    <div className="feedback-workspace">
      <section className="feedback-compose" aria-labelledby="feedback-compose-title">
        <h2 id="feedback-compose-title">한마디 남기기 <ArrowUpRight size={18} aria-hidden="true" /></h2>
        <form onSubmit={submit}>
          <div className="feedback-field">
            <label htmlFor="feedback-name">이름 <span>닉네임도 좋아요</span></label>
            <input id="feedback-name" name="name" autoComplete="nickname" maxLength={30} required value={name} onChange={(event) => setName(event.target.value)} placeholder="어떤 이름으로 남길까요?" disabled={pending} />
          </div>
          <div className="feedback-field">
            <label htmlFor="feedback-content">피드백 내용</label>
            <textarea id="feedback-content" name="content" required rows={6} value={content} onChange={(event) => setContent(event.target.value)} placeholder="좋았던 점, 아쉬웠던 점, 바라는 점을 들려주세요." aria-describedby="feedback-count feedback-public" aria-invalid={overLimit || undefined} disabled={pending} />
            <div id="feedback-count" className={`feedback-count${overLimit ? " is-over" : ""}`}><span>{overLimit ? "200자 이내로 줄여 주세요." : "짧은 한마디도 환영해요."}</span><span>{count}<span className="feedback-count__limit"> / 200자</span></span></div>
          </div>
          <p id="feedback-public" className="feedback-public">이름과 내용은 모두에게 공개됩니다.</p>
          <Button className="feedback-submit" type="submit" disabled={pending || overLimit || !name.trim() || !content.trim()}>{pending ? <>등록 중 <LoaderCircle size={16} className="feedback-spinner" aria-hidden="true" /></> : <>피드백 남기기 <ArrowUpRight size={17} aria-hidden="true" /></>}</Button>
          {error && <p className="feedback-message" role="alert">{error}</p>}
          {posted && !error && <p className="feedback-message" role="status"><Check size={15} aria-hidden="true" /> 피드백을 남겼어요. 고맙습니다!</p>}
        </form>
      </section>
      <section className="feedback-entries" aria-labelledby="feedback-entries-title" aria-busy={feedback.isPending}>
        <div className="feedback-entries__heading"><h2 id="feedback-entries-title">남겨주신 이야기</h2><span>최신순</span></div>
        {feedback.isPending && <p className="feedback-empty" role="status">이야기를 불러오고 있어요.</p>}
        {feedback.isError && <div className="feedback-empty" role="alert"><p>피드백을 불러오지 못했어요.</p><Button type="button" className="feedback-text-button" onClick={() => void feedback.refetch()}>다시 불러오기</Button></div>}
        {!feedback.isPending && !feedback.isError && visibleEntries.length === 0 && <div className="feedback-empty"><span className="feedback-empty__mark" aria-hidden="true">“</span><h3>첫 이야기를 기다리고 있어요.</h3><p>에피카의 첫 방명록을 채워 주세요.</p></div>}
        <ol className="feedback-list">{visibleEntries.map((entry) => <li key={entry.id} className={entry.id === posted?.id ? "feedback-entry is-new" : "feedback-entry"}>
          <div className="feedback-entry__meta"><strong>{entry.name}</strong><time dateTime={entry.created_at}>{dateFormat.format(new Date(entry.created_at))}</time></div>
          <p>{entry.content}</p>
        </li>)}</ol>
        {feedback.hasNextPage && <Button className="feedback-more" type="button" onClick={() => void feedback.fetchNextPage()} disabled={feedback.isFetchingNextPage}>{feedback.isFetchingNextPage ? "불러오는 중" : "이전 이야기 더 보기"}<ArrowDown size={15} aria-hidden="true" /></Button>}
      </section>
    </div>
  </div>;
}
