"use client";

import { Toast as BaseToast } from "@base-ui/react/toast";
import { Check, X } from "lucide-react";
import { useEffect } from "react";

export function Toast({ message }: { message: string }) {
  return <BaseToast.Provider timeout={4000}><ToastContent message={message} /></BaseToast.Provider>;
}

function ToastContent({ message }: { message: string }) {
  const { add, toasts } = BaseToast.useToastManager();
  useEffect(() => {
    add({ id: "status", title: "완료", description: message });
  }, [add, message]);
  return <BaseToast.Portal><BaseToast.Viewport className="toast-viewport">{toasts.map((toast) => <BaseToast.Root className="toast" key={toast.id} toast={toast}><BaseToast.Content className="toast__content"><Check size={15} aria-hidden="true" /><div><BaseToast.Title className="toast__title" /><BaseToast.Description className="toast__description" /></div><BaseToast.Close className="toast__close" aria-label="알림 닫기"><X size={14} /></BaseToast.Close></BaseToast.Content></BaseToast.Root>)}</BaseToast.Viewport></BaseToast.Portal>;
}
