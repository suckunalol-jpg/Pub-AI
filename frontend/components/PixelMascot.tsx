"use client";

import React from "react";
import { cn } from "@/lib/utils";
import type { AiPhase } from "./ActionIndicator";

interface PixelMascotProps {
  phase?: AiPhase | "idle" | "response" | string;
  className?: string;
  size?: number;
}

/**
 * PubAI Mascot — pixel-accurate recreation of the blue pixel creature.
 * 
 * Structure (on a 16x16 grid):
 * - Large rectangular head/body block (~10 wide, ~8 tall)
 * - Small ear bumps on top-left and top-right corners (2px wide, 2px tall)
 * - Two black 2x2 square eyes in the upper portion, well spaced apart
 * - Side arm/bumps extending from mid-body on both sides
 * - Four legs at bottom: two on each side with a gap in the middle
 * - Subtle mouth indent below eyes
 * 
 * Base color: ~#5b6abf (medium blue matching the user's mascot)
 */
export default function PixelMascot({ phase = "idle", className, size = 48 }: PixelMascotProps) {
  let eyeStyle: "normal" | "happy" | "thinking" | "wide" | "determined" | "wink" = "normal";
  let mouthStyle: "neutral" | "smile" | "open" | "dash" = "neutral";
  let showHat = false;
  let showSparks = false;
  let bouncing = false;

  switch (phase) {
    case "idle":
      eyeStyle = "normal";
      mouthStyle = "neutral";
      bouncing = true;
      break;
    case "thinking":
    case "planning":
      eyeStyle = "thinking";
      mouthStyle = "dash";
      break;
    case "analyzing":
    case "reviewing":
      eyeStyle = "wide";
      mouthStyle = "neutral";
      break;
    case "coding":
    case "writing":
    case "writing_file":
    case "formatting":
    case "summarizing":
      eyeStyle = "determined";
      mouthStyle = "dash";
      showHat = true;
      break;
    case "debugging":
      eyeStyle = "wink";
      mouthStyle = "open";
      showSparks = true;
      break;
    case "executing":
    case "spawning_agent":
    case "calling_tool":
      eyeStyle = "wide";
      mouthStyle = "open";
      showSparks = true;
      break;
    case "reading_file":
    case "searching_web":
    case "searching_knowledge":
      eyeStyle = "wide";
      mouthStyle = "neutral";
      break;
    case "response":
      eyeStyle = "happy";
      mouthStyle = "smile";
      break;
    default:
      eyeStyle = "normal";
      mouthStyle = "neutral";
      break;
  }

  // Colors matching the user's mascot exactly
  const body = "#5b6abf";
  const bodyDark = "#4c59a8";
  const bodyLight = "#6b7ad0";
  const eyeColor = "#1a1a2e";
  const mouthColor = "#4a4a80";

  return (
    <div
      className={cn(
        "relative inline-flex items-center justify-center select-none",
        bouncing && "animate-bounce-slow",
        className
      )}
      style={{ width: size, height: size }}
    >
      <svg
        viewBox="0 0 16 16"
        width={size}
        height={size}
        shapeRendering="crispEdges"
        xmlns="http://www.w3.org/2000/svg"
      >
        {/* ══ MAIN BODY/HEAD BLOCK ══ */}
        {/* Core rectangle: columns 3-12, rows 3-10 */}
        <rect x="3" y="3" width="10" height="8" fill={body} />

        {/* ══ EAR BUMPS ══ */}
        {/* Left ear: cols 3-4, rows 1-2 */}
        <rect x="3" y="1" width="2" height="2" fill={body} />
        {/* Right ear: cols 11-12, rows 1-2 */}
        <rect x="11" y="1" width="2" height="2" fill={body} />

        {/* ══ SIDE ARM BUMPS ══ */}
        {/* Left arm: col 2, rows 5-7 */}
        <rect x="2" y="5" width="1" height="3" fill={body} />
        {/* Right arm: col 13, rows 5-7 */}
        <rect x="13" y="5" width="1" height="3" fill={body} />

        {/* ══ FOUR LEGS ══ */}
        {/* Left-outer leg: cols 4-5, rows 11-13 */}
        <rect x="4" y="11" width="1" height="3" fill={body} />
        {/* Left-inner leg: cols 6-7, rows 11-12 */}
        <rect x="6" y="11" width="1" height="3" fill={body} />
        {/* Right-inner leg: cols 9-10, rows 11-12 */}
        <rect x="9" y="11" width="1" height="3" fill={body} />
        {/* Right-outer leg: cols 11-12, rows 11-13 */}
        <rect x="11" y="11" width="1" height="3" fill={body} />

        {/* ══ SHADING ══ */}
        {/* Top highlight */}
        <rect x="4" y="3" width="8" height="1" fill={bodyLight} opacity="0.3" />
        {/* Bottom shadow */}
        <rect x="3" y="10" width="10" height="1" fill={bodyDark} />

        {/* ══ EYES ══ */}
        {eyeStyle === "normal" && (
          <>
            {/* Left eye: 2x2 at cols 5-6, rows 5-6 */}
            <rect x="5" y="5" width="2" height="2" fill={eyeColor} />
            {/* Right eye: 2x2 at cols 9-10, rows 5-6 */}
            <rect x="9" y="5" width="2" height="2" fill={eyeColor} />
          </>
        )}
        {eyeStyle === "happy" && (
          <>
            {/* Happy U-shape eyes */}
            <rect x="5" y="5" width="1" height="2" fill={eyeColor} />
            <rect x="6" y="6" width="1" height="1" fill={eyeColor} />
            <rect x="9" y="6" width="1" height="1" fill={eyeColor} />
            <rect x="10" y="5" width="1" height="2" fill={eyeColor} />
          </>
        )}
        {eyeStyle === "thinking" && (
          <>
            {/* Left eye raised, right eye lower */}
            <rect x="5" y="4" width="2" height="2" fill={eyeColor} />
            <rect x="9" y="6" width="2" height="1" fill={eyeColor} />
          </>
        )}
        {eyeStyle === "wide" && (
          <>
            {/* Bigger 2x3 eyes with shine */}
            <rect x="5" y="4" width="2" height="3" fill={eyeColor} />
            <rect x="5" y="4" width="1" height="1" fill="#ffffff" opacity="0.4" />
            <rect x="9" y="4" width="2" height="3" fill={eyeColor} />
            <rect x="9" y="4" width="1" height="1" fill="#ffffff" opacity="0.4" />
          </>
        )}
        {eyeStyle === "determined" && (
          <>
            {/* Flat-top brow line over eyes */}
            <rect x="4" y="4" width="3" height="1" fill={bodyDark} />
            <rect x="5" y="5" width="2" height="2" fill={eyeColor} />
            <rect x="9" y="4" width="3" height="1" fill={bodyDark} />
            <rect x="9" y="5" width="2" height="2" fill={eyeColor} />
          </>
        )}
        {eyeStyle === "wink" && (
          <>
            {/* Left eye normal, right eye winking (line) */}
            <rect x="5" y="5" width="2" height="2" fill={eyeColor} />
            <rect x="9" y="6" width="2" height="1" fill={eyeColor} />
          </>
        )}

        {/* ══ MOUTH ══ */}
        {mouthStyle === "neutral" && (
          <rect x="7" y="8" width="2" height="1" fill={mouthColor} />
        )}
        {mouthStyle === "smile" && (
          <>
            <rect x="6" y="8" width="4" height="1" fill={mouthColor} />
            <rect x="7" y="9" width="2" height="1" fill={mouthColor} />
          </>
        )}
        {mouthStyle === "open" && (
          <rect x="7" y="8" width="2" height="2" fill={mouthColor} />
        )}
        {mouthStyle === "dash" && (
          <rect x="7" y="8" width="2" height="1" fill={mouthColor} />
        )}

        {/* ══ ACCESSORIES ══ */}
        {/* Hard hat for coding phases */}
        {showHat && (
          <>
            <rect x="3" y="0" width="10" height="2" fill="#fbbf24" />
            <rect x="6" y="-1" width="4" height="1" fill="#f59e0b" />
          </>
        )}

        {/* Sparks for executing/debugging */}
        {showSparks && (
          <>
            <rect x="1" y="3" width="1" height="1" fill="#facc15" opacity="0.9" />
            <rect x="14" y="2" width="1" height="1" fill="#facc15" opacity="0.7" />
            <rect x="0" y="6" width="1" height="1" fill="#facc15" opacity="0.5" />
            <rect x="15" y="5" width="1" height="1" fill="#facc15" opacity="0.8" />
          </>
        )}
      </svg>
    </div>
  );
}
