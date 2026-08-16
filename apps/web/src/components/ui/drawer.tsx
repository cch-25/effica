"use client";

import { X } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "./button";

export function Drawer({ open, title, children, onClose }: { open: boolean; title: string; children: ReactNode; onClose: () => void }) {
  if (!open) return null;
  return <div className="drawer-layer"><button className="drawer-layer__backdrop" aria-label="드로어 닫기" onClick={onClose} /><aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title"><div className="dialog__head"><h2 id="drawer-title">{title}</h2><Button variant="ghost" aria-label="드로어 닫기" onClick={onClose}><X size={20} /></Button></div><div className="drawer__body">{children}</div></aside></div>;
}
