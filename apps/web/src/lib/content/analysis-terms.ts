export const analysisTerms = {
  bias: {
    label: "편향성",
    description: "기사의 주장과 강조점이 좌우 어느 관점에 가까운지 AI가 평가한 값입니다. 사실 여부나 기사 품질 점수가 아닙니다.",
  },
  sensationalism: {
    label: "과장성",
    description: "제목과 문장의 자극적이거나 감정적인 표현 강도입니다. 내용의 사실 여부를 뜻하지 않습니다.",
  },
  confidence: {
    label: "분석 신뢰도",
    description: "현재 근거로 AI 분석 결과가 얼마나 안정적인지 나타냅니다. 출처 신뢰도나 정답일 확률을 뜻하지 않습니다.",
  },
  biasRange: {
    label: "편향 범위",
    description: "현재 지도에 표시된 기사 가운데 가장 낮은 편향성 값부터 가장 높은 값까지의 범위입니다.",
  },
  averageSensationalism: {
    label: "평균 과장성",
    description: "현재 표시된 기사 중 과장성을 측정할 수 있는 기사들의 평균 표현 강도입니다.",
  },
  averageConfidence: {
    label: "평균 신뢰도",
    description: "현재 표시된 기사들의 AI 분석 신뢰도를 평균한 값입니다. 기사 품질의 평균이 아닙니다.",
  },
} as const;
