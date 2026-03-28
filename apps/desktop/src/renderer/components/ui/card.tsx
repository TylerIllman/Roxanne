import type { HTMLAttributes, PropsWithChildren } from "react";

import { cn } from "../../lib/cn";

type DivProps = PropsWithChildren<HTMLAttributes<HTMLDivElement>>;

export function Card({ className, children, ...props }: DivProps) {
  return (
    <div className={cn("rounded-3xl border border-zinc-200 bg-white shadow-[0_24px_48px_rgba(16,24,40,0.06)]", className)} {...props}>
      {children}
    </div>
  );
}

export function CardHeader({ className, children, ...props }: DivProps) {
  return (
    <div className={cn("flex flex-col gap-2 p-6", className)} {...props}>
      {children}
    </div>
  );
}

export function CardTitle({ className, children, ...props }: DivProps) {
  return (
    <div className={cn("text-[1.1rem] font-semibold tracking-[-0.02em] text-zinc-950", className)} {...props}>
      {children}
    </div>
  );
}

export function CardDescription({ className, children, ...props }: DivProps) {
  return (
    <div className={cn("text-sm leading-6 text-zinc-500", className)} {...props}>
      {children}
    </div>
  );
}

export function CardContent({ className, children, ...props }: DivProps) {
  return (
    <div className={cn("flex flex-col gap-2 p-6 pt-0", className)} {...props}>
      {children}
    </div>
  );
}

export function CardFooter({ className, children, ...props }: DivProps) {
  return (
    <div className={cn("flex flex-col gap-2 p-6 pt-0", className)} {...props}>
      {children}
    </div>
  );
}
