import { useEffect, useRef } from "react";

interface Dot {
  x: number;
  y: number;
  r: number;
  phase: number;
  speed: number;
  driftX: number;
  driftY: number;
}

const DOT_DENSITY = 1 / 2200; // one dot per ~2200 px² of photo

const makeDots = (width: number, height: number): Dot[] =>
  Array.from({ length: Math.round(Math.min(160, Math.max(40, width * height * DOT_DENSITY))) }, () => ({
    x: Math.random() * width,
    y: Math.random() * height,
    r: 1.2 + Math.random() * 1.6,
    phase: Math.random() * Math.PI * 2,
    speed: 0.0012 + Math.random() * 0.0022,
    driftX: (Math.random() - 0.5) * 0.012,
    driftY: (Math.random() - 0.5) * 0.012,
  }));

/**
 * Google Lens-style "looking" overlay: the photo dims a little and soft points of light
 * twinkle and drift across it while the scan runs. Static under reduced motion.
 */
const ScanSparkles = () => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let dots: Dot[] = [];
    let frame = 0;
    let width = 0;
    let height = 0;

    const resize = () => {
      const ratio = window.devicePixelRatio || 1;
      width = canvas.clientWidth;
      height = canvas.clientHeight;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      dots = makeDots(width, height);
    };

    const draw = (time: number) => {
      context.clearRect(0, 0, width, height);
      for (const dot of dots) {
        if (!reduceMotion) {
          dot.x = (dot.x + dot.driftX * 16 + width) % width;
          dot.y = (dot.y + dot.driftY * 16 + height) % height;
        }
        const twinkle = reduceMotion ? 0.7 : (Math.sin(time * dot.speed + dot.phase) + 1) / 2;
        const alpha = 0.1 + twinkle * twinkle * 0.9;
        const glow = dot.r * (2.5 + twinkle * 2);
        const gradient = context.createRadialGradient(dot.x, dot.y, 0, dot.x, dot.y, glow);
        gradient.addColorStop(0, `rgba(255, 255, 255, ${alpha})`);
        gradient.addColorStop(0.35, `rgba(64, 214, 184, ${alpha * 0.7})`);
        gradient.addColorStop(1, "rgba(64, 214, 184, 0)");
        context.fillStyle = gradient;
        context.beginPath();
        context.arc(dot.x, dot.y, glow, 0, Math.PI * 2);
        context.fill();
      }
      if (!reduceMotion) frame = requestAnimationFrame(draw);
    };

    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    frame = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, []);

  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 animate-in fade-in duration-300">
      <div className="absolute inset-0 bg-[hsl(228_30%_8%/0.3)]" />
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />
    </div>
  );
};

export default ScanSparkles;
