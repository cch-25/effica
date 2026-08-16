"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Toast } from "@/components/ui/toast";

export function PrivacyActions() {
  const [dialog, setDialog] = useState<"withdraw" | "delete" | null>(null); const [status, setStatus] = useState("");
  const confirm = () => { setStatus(dialog === "delete" ? "계정 삭제 작업이 pending 상태로 접수되었습니다." : "정치 민감정보 동의가 철회되어 개인화와 행동 프로필이 중지되었습니다."); setDialog(null); };
  return <><section className="card card--padded"><div className="privacy-action"><div><strong>정치 민감정보 별도 동의</strong><p>활성 · consent-political-v3</p></div><Button variant="secondary" onClick={() => setDialog("withdraw")}>동의 철회</Button></div><div className="privacy-action"><div><strong>내 데이터 내보내기</strong><p>JSON 아카이브를 비동기 작업으로 준비합니다.</p></div><Button variant="secondary" onClick={() => setStatus("데이터 내보내기 작업이 pending 상태로 접수되었습니다.")}>내보내기 요청</Button></div><div className="privacy-action"><div><strong>계정 삭제</strong><p>세션·공유 토큰은 즉시 폐기되고 법적 보존 조건을 확인한 뒤 개인 데이터가 파기 또는 비식별화됩니다.</p></div><Button variant="danger" onClick={() => setDialog("delete")}>계정 삭제 요청</Button></div></section><Dialog open={dialog !== null} onClose={() => setDialog(null)} title={dialog === "delete" ? "계정을 삭제할까요?" : "별도 동의를 철회할까요?"}><p>{dialog === "delete" ? "‘계정 삭제’를 입력한 것으로 간주하고 비동기 삭제 작업을 시작합니다." : "철회 즉시 행동 프로필과 개인화가 중지됩니다. 비개인화 균형 피드는 계속 이용할 수 있습니다."}</p><div className="form-actions"><Button variant="secondary" onClick={() => setDialog(null)}>취소</Button><Button variant={dialog === "delete" ? "danger" : "primary"} onClick={confirm}>확인</Button></div></Dialog>{status && <Toast message={status} />}</>;
}
