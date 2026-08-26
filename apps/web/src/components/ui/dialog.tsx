"use client";

import { Dialog as BaseDialog } from "@base-ui/react/dialog";
import type { ReactNode } from "react";
import { X } from "lucide-react";

export function Dialog({ open, title, description = "선택한 작업의 내용을 확인하고 계속할지 결정하세요.", children, onClose }: { open: boolean; title: string; description?: string; children: ReactNode; onClose: () => void }) {
  return (
    <BaseDialog.Root open={open} onOpenChange={(nextOpen) => { if (!nextOpen) onClose(); }}>
      <BaseDialog.Portal>
        <BaseDialog.Backdrop className="dialog-backdrop" />
        <BaseDialog.Viewport className="dialog-viewport">
          <BaseDialog.Popup className="dialog">
            <div className="dialog__head">
              <div><BaseDialog.Title>{title}</BaseDialog.Title><BaseDialog.Description className="dialog__description">{description}</BaseDialog.Description></div>
              <BaseDialog.Close className="button button--ghost button--icon" aria-label="대화상자 닫기"><X size={16} /></BaseDialog.Close>
            </div>
            <div className="dialog__body">{children}</div>
          </BaseDialog.Popup>
        </BaseDialog.Viewport>
      </BaseDialog.Portal>
    </BaseDialog.Root>
  );
}
