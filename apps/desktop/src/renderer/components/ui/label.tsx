import type { LabelHTMLAttributes, PropsWithChildren } from "react";

import { cn } from "../../lib/cn";

type LabelProps = PropsWithChildren<LabelHTMLAttributes<HTMLLabelElement>>;

export function Label({ className, children, ...props }: LabelProps) {
  return (
    <label className={cn("text-sm font-medium text-zinc-950", className)} {...props}>
      {children}
    </label>
  );
}
