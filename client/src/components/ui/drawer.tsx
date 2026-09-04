"use client";

import { Drawer as BaseDrawer } from "@base-ui/react/drawer";
import { X } from "lucide-react";
import type { ReactNode } from "react";

export function Drawer({ open, title, description = "표시할 조건을 선택한 뒤 결과에 적용하세요.", children, onClose }: { open: boolean; title: string; description?: string; children: ReactNode; onClose: () => void }) {
  return (
    <BaseDrawer.Root open={open} onOpenChange={(nextOpen) => { if (!nextOpen) onClose(); }} swipeDirection="right">
      <BaseDrawer.Portal>
        <BaseDrawer.Backdrop className="drawer-backdrop" />
        <BaseDrawer.Viewport className="drawer-viewport">
          <BaseDrawer.Popup className="drawer">
            <BaseDrawer.Content>
              <div className="dialog__head">
                <div><BaseDrawer.Title>{title}</BaseDrawer.Title><BaseDrawer.Description className="dialog__description">{description}</BaseDrawer.Description></div>
                <BaseDrawer.Close className="button button--ghost button--icon" aria-label="드로어 닫기"><X size={16} /></BaseDrawer.Close>
              </div>
              <div className="drawer__body">{children}</div>
            </BaseDrawer.Content>
          </BaseDrawer.Popup>
        </BaseDrawer.Viewport>
      </BaseDrawer.Portal>
    </BaseDrawer.Root>
  );
}
