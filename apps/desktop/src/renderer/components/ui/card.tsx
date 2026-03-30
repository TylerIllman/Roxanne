import type { HTMLAttributes, PropsWithChildren } from "react";

import { cn } from "../../lib/cn";

type DivProps = PropsWithChildren<HTMLAttributes<HTMLDivElement>>;

export function Card({ className, children, ...props }: DivProps) {
  return (
    <div className={cn("rounded-lg border border-zinc-200 bg-white shadow-sm", className)} {...props}>
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
    <div className={cn("text-base font-semibold text-zinc-900", className)} {...props}>
      {children}
    </div>
  );
}

export function CardDescription({ className, children, ...props }: DivProps) {
  return (
    <div className={cn("text-sm text-zinc-500", className)} {...props}>
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
