import type { ButtonHTMLAttributes, PropsWithChildren } from "react";

import { cn } from "../../lib/cn";

type ButtonVariant = "default" | "secondary" | "outline" | "ghost";
type ButtonSize = "default" | "sm" | "lg" | "icon";

type ButtonProps = PropsWithChildren<
  ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: ButtonVariant;
    size?: ButtonSize;
  }
>;

export function Button({
  className,
  variant = "default",
  size = "default",
  type = "button",
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-all outline-none",
        "focus-visible:ring-4 focus-visible:ring-black/10 disabled:pointer-events-none disabled:opacity-50",
        "data-[state=open]:bg-zinc-100",
        variant === "default" &&
          "bg-black text-white shadow-sm hover:bg-zinc-900",
        variant === "secondary" &&
          "bg-zinc-100 text-zinc-950 hover:bg-zinc-200",
        variant === "outline" &&
          "border border-zinc-200 bg-white text-zinc-950 hover:bg-zinc-50 hover:border-zinc-300",
        variant === "ghost" &&
          "text-zinc-950 hover:bg-zinc-100",
        size === "default" && "h-10 px-4 py-2",
        size === "sm" && "h-8 rounded-md px-3 text-xs",
        size === "lg" && "h-11 rounded-md px-6",
        size === "icon" && "h-9 w-9",
        className
      )}
      type={type}
      {...props}
    >
      {children}
    </button>
  );
}
