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
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div className="inline-flex items-center gap-2 rounded-md bg-muted px-3 py-1 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
          Processing prescription
        </div>
        <h2 className="text-2xl font-semibold text-foreground">Analyzing your image</h2>
        <p className="text-sm text-muted-foreground">
          Please keep this window open while extraction and validation complete.
        </p>
      </div>

      <div className="space-y-3">
        <Progress value={progress} className="h-2" />
        <div className="text-right text-sm font-medium text-primary">{Math.round(progress)}%</div>
      </div>

      <div className="space-y-2">
        {steps.map((step, index) => (
          <div
            key={step.label}
            className={`flex items-center gap-3 rounded-md border px-3 py-2 transition-colors ${
              index < currentStep
                ? "bg-accent/10 border-accent/20"
                : index === currentStep
                  ? "bg-primary/10 border-primary/20"
                  : "bg-muted/40"
            }`}
          >
            {index < currentStep ? (
              <CheckCircle2 className="h-4 w-4 text-accent" />
            ) : index === currentStep ? (
              <Loader2 className="h-4 w-4 animate-spin text-primary" />
            ) : (
              <FileText className="h-4 w-4 text-muted-foreground" />
            )}
            <span className="text-sm text-foreground">{step.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

export default ProcessingScreen;
