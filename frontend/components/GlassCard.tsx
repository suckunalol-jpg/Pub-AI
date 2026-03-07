"use client";

import { cn } from "@/lib/utils";

interface GlassCardProps {
  children: React.ReactNode;
  className?: string;
  hover?: boolean;
}

export default function GlassCard({ children, className, hover = false }: GlassCardProps) {
  return (
    <div
      className={cn(
        "bg-black/30 backdrop-blur-xl border border-white/10 rounded-2xl",
        hover && "hover:bg-white/10 hover:border-accent/30 transition-all duration-200",
        className
      )}
    >
      {children}
    </div>
  );
}
