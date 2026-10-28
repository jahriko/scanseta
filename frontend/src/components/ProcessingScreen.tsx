import StatusGlyph from "@/components/StatusGlyph";

interface ProcessingStep {
  label: string;
  duration: number;
}

interface ProcessingScreenProps {
  simulated?: boolean;
  progress: number;
  currentStep: number;
  steps: ProcessingStep[];
}

const ProcessingScreen = ({ progress, currentStep, steps, simulated = false }: ProcessingScreenProps) => {
  const stepShare = 100 / steps.length;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-foreground">
          {simulated ? "Replaying Sample Prescription" : "Analyzing Prescription"}
        </h2>
        <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">
          {simulated ? "Replaying prepared results for this image." : "Reading the handwriting first, then checking FDA and PNDF records."}
        </p>
      </div>

      <div>
        <div className="flex items-baseline justify-between text-[13px]">
          <span className="text-muted-foreground">Progress</span>
          <span className="tnum font-medium text-foreground">{Math.round(progress)}%</span>
        </div>
        <div
          className="mt-2 h-1 overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-valuenow={Math.round(progress)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Scan progress"
        >
          <div
            className="h-full rounded-full bg-primary transition-[width] duration-200 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      <ol className="divide-y divide-border border-y border-border">
        {steps.map((step, index) => {
          const isDone = index < currentStep;
          const isActive = index === currentStep;
          const fraction = isActive ? Math.min(1, Math.max(0.08, (progress - index * stepShare) / stepShare)) : 0;
          return (
            <li key={step.label} className="flex items-center gap-3 py-2.5">
              <StatusGlyph state={isDone ? "done" : isActive ? "progress" : "todo"} fraction={fraction} />
              <span className={`text-[13px] ${isDone || isActive ? "text-foreground" : "text-muted-foreground"} ${isActive ? "font-medium" : ""}`}>
                {step.label}
              </span>
              <span className="tnum ml-auto text-xs text-muted-foreground">
                {isDone ? "Done" : `~${Math.max(1, Math.round(step.duration / 1000))}s`}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
};

export default ProcessingScreen;
