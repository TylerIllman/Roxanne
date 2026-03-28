import type { HTMLAttributes } from "react";

import { cn } from "../../lib/cn";

type SeparatorProps = HTMLAttributes<HTMLDivElement>;

export function Separator({ className, ...props }: SeparatorProps) {
  return <div className={cn("h-px w-full bg-zinc-200", className)} {...props} />;
}
