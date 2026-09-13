import type { Metadata } from "next";
import { FeedbackGuestbook } from "@/features/feedback/feedback-guestbook";
import "./feedback.css";

export const metadata: Metadata = { title: "피드백", description: "에피카를 읽고 느낀 점을 남기는 독자 방명록" };

export default function FeedbackPage() {
  return <FeedbackGuestbook />;
}
