"use client";

import { Toast as BaseToast } from "@base-ui/react/toast";
import { Check, X } from "lucide-react";
import { useEffect } from "react";

export function Toast({ message, title = "완료" }: { message: string; title?: string }) {
  return <BaseToast.Provider timeout={4000}><ToastContent message={message} title={title} /></BaseToast.Provider>;
}

function ToastContent({ message, title }: { message: string; title: string }) {
  const { add, toasts } = BaseToast.useToastManager();
  useEffect(() => {
    add({ id: "status", title, description: message });
  }, [add, message, title]);
  return <BaseToast.Portal><BaseToast.Viewport className="toast-viewport">{toasts.map((toast) => <BaseToast.Root className="toast" key={toast.id} toast={toast}><BaseToast.Content className="toast__content"><Check size={15} aria-hidden="true" /><div><BaseToast.Title className="toast__title" /><BaseToast.Description className="toast__description" /></div><BaseToast.Close className="toast__close" aria-label="알림 닫기"><X size={14} /></BaseToast.Close></BaseToast.Content></BaseToast.Root>)}</BaseToast.Viewport></BaseToast.Portal>;
}
