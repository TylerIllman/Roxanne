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
        "inline-flex items-center justify-center whitespace-nowrap rounded-lg text-sm font-medium transition-colors outline-none",
        "focus-visible:ring-2 focus-visible:ring-zinc-900/20 disabled:pointer-events-none disabled:opacity-50",
        variant === "default" &&
          "bg-zinc-900 text-white shadow-sm hover:bg-zinc-800",
        variant === "secondary" &&
          "bg-zinc-100 text-zinc-900 hover:bg-zinc-200",
        variant === "outline" &&
          "border border-zinc-200 bg-white text-zinc-900 hover:bg-zinc-50",
        variant === "ghost" &&
          "text-zinc-900 hover:bg-zinc-100",
        size === "default" && "h-9 px-4 py-2",
        size === "sm" && "h-8 px-3 text-xs",
        size === "lg" && "h-11 px-6",
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
