import type { Metadata } from "next";
import { AlgoInfographic } from "@/features/algo/algo-infographic";

export const metadata: Metadata = {
  title: "알고리즘",
  description: "뉴스 수집과 원문 검증부터 관점 좌표 산출, 개인화 추천까지 에피카 알고리즘의 작동 원리를 설명합니다.",
};

export default function AlgorithmPage() {
  return <AlgoInfographic />;
}
