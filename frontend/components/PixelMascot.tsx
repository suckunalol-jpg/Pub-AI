import React from "react";
import { cn } from "@/lib/utils";
import type { AiPhase } from "./ActionIndicator";

interface PixelMascotProps {
  phase?: AiPhase | "idle" | "response" | string;
  className?: string;
  size?: number;
}

export default function PixelMascot({ phase = "idle", className, size = 32 }: PixelMascotProps) {
  // Map AI phases to emotions/actions
  let expression = "smile";
  let accessory = "none";
  let animation = "";

  switch (phase) {
    case "thinking":
    case "planning":
      expression = "thinking";
      animation = "animate-pulse";
      break;
    case "analyzing":
    case "reviewing":
      expression = "focused";
      accessory = "monocle";
      break;
    case "coding":
    case "writing":
    case "writing_file":
    case "formatting":
    case "summarizing":
      expression = "focused";
      accessory = "keyboard";
      animation = "animate-bounce-slow";
      break;
    case "debugging":
      expression = "squint";
      accessory = "bug";
      break;
    case "executing":
    case "spawning_agent":
    case "calling_tool":
      expression = "excited";
      animation = "animate-bounce";
      break;
    case "reading_file":
    case "searching_web":
    case "searching_knowledge":
      expression = "wide";
      accessory = "magnifier";
      break;
    case "response":
      expression = "happy";
      break;
    case "idle":
    default:
      expression = "smile";
      break;
  }

  // Base Pixel Art SVG using a 16x16 grid
  // We define groups for face/eyes/mouth/accessories
  return (
    <div
      className={cn("relative inline-flex items-center justify-center", animation, className)}
      style={{ width: size, height: size }}
    >
      <svg
        viewBox="0 0 16 16"
        width={size}
        height={size}
        shapeRendering="crispEdges"
        xmlns="http://www.w3.org/2000/svg"
      >
        {/* Shadow */}
        <path d="M4,15 h8 v1 h-8 z" fill="#000000" opacity="0.4" />

        {/* Body (Screen / Robot Face) */}
        {/* Outer border */}
        <path d="M3,3 h10 v1 h1 v8 h-1 v1 h-10 v-1 h-1 v-8 h1 z" fill="#182e4c" />
        <path d="M4,4 h8 v8 h-8 z" fill="#0a1324" />
        
        {/* Highlight inner frame */}
        <path d="M4,4 h8 v1 h-8 z M4,4 v8 h1 v-8 z" fill="#3b5b7b" opacity="0.5" />

        {/* EYES based on expression */}
        {expression === "smile" && (
          <path d="M5,6 h2 v2 h-2 z M9,6 h2 v2 h-2 z" fill="#5b8bb8" />
        )}
        
        {expression === "happy" && (
          <path d="M5,6 h2 v1 h-2 z M5,7 h1 v1 h-1 z  M9,6 h2 v1 h-2 z M10,7 h1 v1 h-1 z" fill="#5b8bb8" />
        )}

        {expression === "thinking" && (
          <path d="M5,5 h2 v2 h-2 z M9,6 h2 v2 h-2 z" fill="#5b8bb8" />
        )}

        {expression === "focused" && (
          <path d="M5,7 h2 v1 h-2 z M9,7 h2 v1 h-2 z" fill="#5b8bb8" />
        )}

        {expression === "squint" && (
          <path d="M5,6 h2 v1 h-2 z M9,7 h2 v1 h-2 z" fill="#f87171" />
        )}

        {expression === "wide" && (
          <path d="M5,5 h2 v3 h-2 z M9,5 h2 v3 h-2 z M6,6 h1 v1 h-1 z M10,6 h1 v1 h-1 z" fill="#5b8bb8" />
        )}

        {expression === "excited" && (
          <path d="M5,6 h2 v2 h-2 z M9,6 h2 v2 h-2 z" fill="#facc15" />
        )}

        {/* MOUTH based on expression */}
        {(expression === "smile" || expression === "happy") && (
          <path d="M6,10 h4 v1 h-4 z" fill="#5b8bb8" opacity="0.8" />
        )}
        {(expression === "excited" || expression === "wide") && (
          <path d="M6,9 h4 v2 h-4 z" fill="#facc15" opacity="0.8" />
        )}
        {expression === "thinking" && (
          <path d="M7,10 h2 v1 h-2 z" fill="#5b8bb8" opacity="0.7" />
        )}
        {expression === "focused" && (
          <path d="M6,10 h4 v1 h-4 z" fill="#5b8bb8" opacity="0.5" />
        )}
        {expression === "squint" && (
          <path d="M6,10 h3 v1 h-3 z M9,9 h1 v1 h-1 z" fill="#f87171" opacity="0.8" />
        )}

        {/* ACCESSORIES */}
        {accessory === "magnifier" && (
          <path d="M9,4 h3 v3 h-3 z M10,5 h1 v1 h-1 z M11,6 h1 v1 h-1 z M12,7 h1 v1 h-1 z M13,8 h1 v1 h-1 z" fill="#9ca3af" />
        )}
        {accessory === "keyboard" && (
          // Tiny keyboard prop overlay at bottom
          <path d="M3,12 h10 v2 h-10 z M4,12 h1 v1 h-1 z M6,12 h1 v1 h-1 z M8,12 h1 v1 h-1 z M10,12 h1 v1 h-1 z M12,12 h1 v1 h-1 z M5,13 h4 v1 h-4 z M10,13 h2 v1 h-2 z" fill="#cbd5e1" opacity="0.9" />
        )}
        {accessory === "monocle" && (
          <path d="M8,4 h4 v4 h-4 z M9,5 h2 v2 h-2 z M11,7 h1 v1 h-1 z" fill="#fbbf24" opacity="0.9" />
        )}
        {accessory === "bug" && (
          <path d="M3,3 h2 v2 h-2 z M4,4 h1 v1 h-1 z M11,3 h2 v2 h-2 z" fill="#ef4444" opacity="0.8" />
        )}
      </svg>
    </div>
  );
}
