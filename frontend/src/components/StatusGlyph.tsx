import { cn } from "@/lib/utils";

export type GlyphState = "todo" | "progress" | "done" | "review" | "missing" | "pending";

interface StatusGlyphProps {
  state: GlyphState;
  /** 0..1, used by "progress" to fill the pie. */
  fraction?: number;
  size?: number;
  className?: string;
  /** Accessible label; omit when a visible text label sits next to the glyph. */
  label?: string;
}

const tone: Record<GlyphState, string> = {
  todo: "text-muted-foreground/60",
  progress: "text-primary",
  done: "text-verified",
  review: "text-review",
  missing: "text-destructive",
  pending: "text-muted-foreground",
};

/**
 * One glyph family for every status in the app: an outlined circle that fills as work completes.
 * Each state also differs in shape (dash, pie, check, bang, cross), so colour is never the only signal.
 */
const StatusGlyph = ({ state, fraction = 0, size = 16, className, label }: StatusGlyphProps) => {
  const r = 6.25;
  const pieR = 3.1;
  const circumference = 2 * Math.PI * pieR;
  const clamped = Math.max(0, Math.min(1, fraction));

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className={cn("shrink-0", tone[state], state === "pending" && "spin-slow", className)}
    >
      {state === "todo" || state === "pending" ? (
        <circle cx="8" cy="8" r={r} stroke="currentColor" strokeWidth="1.5" strokeDasharray="2.4 2.2" />
      ) : state === "progress" ? (
        <>
          <circle cx="8" cy="8" r={r} stroke="currentColor" strokeWidth="1.5" />
          <circle
            cx="8"
            cy="8"
            r={pieR}
            stroke="currentColor"
            strokeWidth={pieR * 2}
            strokeDasharray={`${circumference * clamped} ${circumference}`}
            transform="rotate(-90 8 8)"
            style={{ transition: "stroke-dasharray 200ms cubic-bezier(0.16, 1, 0.3, 1)" }}
          />
        </>
      ) : (
        <>
          <circle cx="8" cy="8" r="7" fill="currentColor" />
          {state === "done" && (
            <path d="M5 8.2 7.1 10.2 11 6" stroke="white" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          )}
          {state === "review" && (
            <>
              <path d="M8 4.6v4.2" stroke="white" strokeWidth="1.7" strokeLinecap="round" />
              <circle cx="8" cy="11.1" r="1" fill="white" />
            </>
          )}
          {state === "missing" && (
            <path d="m5.6 5.6 4.8 4.8m0-4.8-4.8 4.8" stroke="white" strokeWidth="1.6" strokeLinecap="round" />
          )}
        </>
      )}
    </svg>
  );
};

export default StatusGlyph;
