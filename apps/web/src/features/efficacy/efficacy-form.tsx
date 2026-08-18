"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Toast } from "@/components/ui/toast";
import { Slider } from "@/components/ui/slider";
import { apiRequest } from "@/lib/api/client";
import type { EfficacySubmission, EfficacyView, QuestionnaireVersionView } from "@/lib/api/contracts";

export function EfficacyForm() {
  const [answer, setAnswer] = useState(3);
  const [version, setVersion] = useState<QuestionnaireVersionView | null>(null);
  const [saved, setSaved] = useState<EfficacyView | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    void apiRequest<QuestionnaireVersionView[]>("/questionnaires?kind=efficacy").then((rows) => {
      if (rows[0]) setVersion(rows[0]); else setError("현재 응답 가능한 후속 설문이 없습니다.");
    }).catch(() => setError("후속 설문 버전을 불러오지 못했습니다."));
  }, []);
  const submit = async () => {
    if (!version) return;
    const key = version.keys?.[0] ?? "confidence";
    const body: EfficacySubmission = { questionnaire_version_id: version.id, answers: { [key]: answer * 20 } };
    setBusy(true); setError("");
    try { setSaved(await apiRequest<EfficacyView>("/me/efficacy-responses", { method: "POST", body: JSON.stringify(body) })); }
    catch { setError("후속 설문을 저장하지 못했습니다."); }
    finally { setBusy(false); }
  };
  return <section className="card card--padded"><p className="eyebrow">Follow-up · {version?.version ?? "버전 확인 중"}</p><h2>정치와 정책 이슈를 이해할 수 있다는 자신감이 어느 정도인가요?</h2><Slider id="efficacy" label="전혀 그렇지 않다 1 — 매우 그렇다 5" min={1} max={5} value={answer} onChange={setAnswer} /><Button onClick={submit} disabled={busy || !version}>{busy ? "저장 중…" : "후속 설문 저장"}</Button>{error && <p role="alert" style={{ color: "var(--danger)" }}>{error}</p>}{saved && <Toast message={`정규화 점수 ${saved.normalized_score}점이 저장되었습니다.`} />}</section>;
}
