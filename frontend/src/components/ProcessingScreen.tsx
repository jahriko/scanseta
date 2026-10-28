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
          Analyzing Prescription
        </h2>
        <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">
          {simulated ? "Reading the medicines written on this prescription." : "Reading the handwriting first, then checking FDA and PNDF records."}
        </p>
      </div>

      <div className="flex items-center gap-4">
        <StatusGlyph state="progress" fraction={progress / 100} size={52} />
        <div className="min-w-0 flex-1">
          <p className="tnum text-[32px] font-semibold leading-none tracking-[-0.03em] text-foreground">{Math.round(progress)}%</p>
          <p className="mt-1.5 truncate text-[13px] text-muted-foreground">{steps[currentStep]?.label ?? "Preparing"}</p>
        </div>
        <span className="sr-only" role="progressbar" aria-valuenow={Math.round(progress)} aria-valuemin={0} aria-valuemax={100} aria-label="Scan progress" />
      </div>

      <ol className="divide-y divide-border border-y border-border">
        {steps.map((step, index) => {
          const isDone = index < currentStep;
          const isActive = index === currentStep;
          const fraction = isActive ? Math.min(1, Math.max(0.08, (progress - index * stepShare) / stepShare)) : 0;
          return (
            <li key={step.label} className="flex items-center gap-3 py-3">
              <StatusGlyph state={isDone ? "done" : isActive ? "progress" : "todo"} fraction={fraction} size={18} />
              <span className={`text-sm ${isDone || isActive ? "text-foreground" : "text-muted-foreground"} ${isActive ? "font-medium" : ""}`}>
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
