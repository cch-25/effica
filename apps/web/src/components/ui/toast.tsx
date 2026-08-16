import { CheckCircle2 } from "lucide-react";

export function Toast({ message }: { message: string }) {
  return <div className="toast" role="status"><CheckCircle2 size={18} aria-hidden="true" />{message}</div>;
}
