import type { HTMLAttributes, PropsWithChildren } from "react";

import { cn } from "../../lib/cn";

type BadgeProps = PropsWithChildren<
  HTMLAttributes<HTMLSpanElement> & {
    tone?: "default" | "success" | "muted";
  }
>;

export function Badge({
  className,
  tone = "default",
  children,
  ...props
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center rounded-full border px-2 py-0.5 text-xs font-semibold leading-none",
        tone === "default" && "border-zinc-200 bg-zinc-100 text-zinc-900",
        tone === "muted" && "border-zinc-200 bg-zinc-100 text-zinc-500",
        tone === "success" && "border-emerald-200 bg-emerald-50 text-emerald-700",
        className
      )}
      {...props}
    >
      {children}
    </span>
  );
}
