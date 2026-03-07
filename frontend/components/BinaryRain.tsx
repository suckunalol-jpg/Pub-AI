"use client";

import { useEffect, useRef } from "react";

export default function BinaryRain() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animationId: number;
    const fontSize = 14;
    let columns: number;
    let drops: number[];

    function resize() {
      canvas!.width = window.innerWidth;
      canvas!.height = window.innerHeight;
      columns = Math.floor(canvas!.width / fontSize);
      drops = Array.from({ length: columns }, () =>
        Math.random() * -100
      );
    }

    resize();
    window.addEventListener("resize", resize);

    function draw() {
      ctx!.fillStyle = "rgba(10, 10, 26, 0.08)";
      ctx!.fillRect(0, 0, canvas!.width, canvas!.height);

      for (let i = 0; i < columns; i++) {
        const char = Math.random() > 0.5 ? "1" : "0";
        const x = i * fontSize;
        const y = drops[i] * fontSize;

        // Blue-green tint gradient based on position
        const hue = 160 + Math.sin(i * 0.1) * 30; // oscillate between cyan and green
        const alpha = Math.max(0, 1 - drops[i] / (canvas!.height / fontSize));
        ctx!.fillStyle = `hsla(${hue}, 80%, 60%, ${alpha * 0.4})`;
        ctx!.font = `${fontSize}px monospace`;
        ctx!.fillText(char, x, y);

        if (y > canvas!.height && Math.random() > 0.98) {
          drops[i] = 0;
        }
        drops[i] += 0.5 + Math.random() * 0.3;
      }

      animationId = requestAnimationFrame(draw);
    }

    draw();

    return () => {
      window.removeEventListener("resize", resize);
      cancelAnimationFrame(animationId);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      id="binary-rain-container"
      className="fixed inset-0 z-0 pointer-events-none"
    />
  );
}
