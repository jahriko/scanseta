import { Loader2, FileText, CheckCircle2 } from "lucide-react";
import { Progress } from "@/components/ui/progress";

interface ProcessingStep {
  label: string;
  duration: number;
}

interface ProcessingScreenProps {
  progress: number;
  currentStep: number;
  steps: ProcessingStep[];
}

const ProcessingScreen = ({ progress, currentStep, steps }: ProcessingScreenProps) => {
  const activeStepLabel = steps[currentStep]?.label ?? "Preparing analysis";

  return (
    <div className="space-y-5">
      <div className="rounded-xl border bg-card/90 p-4 shadow-sm">
        <div className="inline-flex items-center gap-2 rounded-full border border-blue-500/30 bg-blue-500/10 px-3 py-1 text-xs font-semibold text-blue-700">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Processing prescription
        </div>
        <h2 className="mt-3 text-2xl font-semibold text-foreground">Analyzing Prescription</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          OCR extraction runs first, then FDA and PNDF validation continue in parallel.
        </p>
      </div>

      <div className="rounded-xl border bg-card p-4 shadow-sm">
        <div className="flex items-end justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Progress</p>
            <p className="text-2xl font-semibold text-foreground">{Math.round(progress)}%</p>
          </div>
          <p className="max-w-[65%] text-right text-xs text-muted-foreground">
            Current step: <span className="font-medium text-foreground">{activeStepLabel}</span>
          </p>
        </div>
        <Progress value={progress} className="mt-3 h-2.5" />
      </div>

      <div className="space-y-2">
        {steps.map((step, index) => (
          <div key={step.label} className="relative">
            <div
              className={`flex items-center gap-3 rounded-xl border px-3 py-3 transition-colors ${
                index < currentStep
                  ? "border-green-500/30 bg-green-500/5"
                  : index === currentStep
                    ? "border-blue-500/40 bg-blue-500/10"
                    : "border-border/80 bg-muted/30"
              }`}
            >
              <div
                className={`grid h-7 w-7 shrink-0 place-items-center rounded-full border ${
                  index < currentStep
                    ? "border-green-500/30 bg-green-500/10"
                    : index === currentStep
                      ? "border-blue-500/30 bg-blue-500/10"
                      : "border-border bg-card/80"
                }`}
              >
                {index < currentStep ? (
                  <CheckCircle2 className="h-4 w-4 text-green-700" />
                ) : index === currentStep ? (
                  <Loader2 className="h-4 w-4 animate-spin text-blue-700" />
                ) : (
                  <FileText className="h-4 w-4 text-muted-foreground" />
                )}
              </div>

              <div className="min-w-0">
                <p className="text-sm font-medium text-foreground">{step.label}</p>
                <p className="text-xs text-muted-foreground">{Math.max(1, Math.round(step.duration / 1000))}s target</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default ProcessingScreen;
