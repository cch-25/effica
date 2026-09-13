import type { Metadata } from "next";
import { FeedbackGuestbook } from "@/features/feedback/feedback-guestbook";
import "./feedback.css";

export const metadata: Metadata = { title: "방명록", description: "에피카에 대한 피드백부터 가벼운 인사까지 자유롭게 남기는 독자 방명록" };

export default function FeedbackPage() {
  return <FeedbackGuestbook />;
}
