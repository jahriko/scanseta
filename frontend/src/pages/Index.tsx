import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Camera, Upload, Scan, Loader2, AlertCircle, Image as ImageIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { toast } from "sonner";
import ProcessingScreen from "@/components/ProcessingScreen";
import ResultsScreen from "@/components/ResultsScreen";
import { getHealth, loadModel, PrescriptionResponse, scanPrescription } from "@/lib/prescription-api";
import { config, validateConfig } from "@/lib/config";

type AppState = "upload" | "processing" | "results" | "error";

const processingSteps = [
  { label: "Uploading image to server", duration: 500 },
  { label: "Analyzing image with AI model", duration: 1500 },
  { label: "Extracting medication information", duration: 1000 },
  { label: "Validating prescription data", duration: 500 },
];

const Index = () => {
  const [appState, setAppState] = useState<AppState>("upload");
  const [imagePreview, setImagePreview] = useState<string>("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [scanResults, setScanResults] = useState<PrescriptionResponse | null>(null);
  const [isModelLoaded, setIsModelLoaded] = useState<boolean>(false);
  const [isLoadingModel, setIsLoadingModel] = useState<boolean>(false);
  const [isCheckingHealth, setIsCheckingHealth] = useState<boolean>(true);
  const [configValid, setConfigValid] = useState<boolean>(true);
  const [scanError, setScanError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [currentStep, setCurrentStep] = useState(0);

  useEffect(() => {
    const checkHealth = async () => {
      const validation = validateConfig();
      setConfigValid(validation.valid);

      if (!validation.valid) {
        validation.errors.forEach((error) => {
          toast.error(error);
        });
        setIsCheckingHealth(false);
        return;
      }

      try {
        const health = await getHealth();
        setIsModelLoaded(health.model_loaded);
        if (!health.model_loaded) {
          toast.info("Model not loaded. Please load the model to start scanning.");
        }
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : "Cannot connect to server. Please ensure the backend is running.";
        toast.error(errorMessage);
        console.error("Health check error:", error);
      } finally {
        setIsCheckingHealth(false);
      }
    };

    checkHealth();
  }, []);

  useEffect(() => {
    if (appState !== "processing" || !selectedFile) {
      return;
    }

    let isActive = true;
    let progressTimer: ReturnType<typeof setInterval> | undefined;

    const processScan = async () => {
      try {
        let currentProgress = 0;
        let stepIndex = 0;
        const totalDuration = processingSteps.reduce((sum, step) => sum + step.duration, 0);
        const interval = 50;

        progressTimer = setInterval(() => {
          if (!isActive) {
            return;
          }

          currentProgress += (interval / totalDuration) * 100;
          if (currentProgress >= 95) {
            currentProgress = 95;
          }

          setProgress(currentProgress);

          const stepThreshold = ((stepIndex + 1) / processingSteps.length) * 100;
          if (currentProgress >= stepThreshold && stepIndex < processingSteps.length - 1) {
            stepIndex++;
            setCurrentStep(stepIndex);
          }
        }, interval);

        const result = await scanPrescription(selectedFile);

        if (!isActive) {
          return;
        }

        if (progressTimer) {
          clearInterval(progressTimer);
        }

        setProgress(100);
        setCurrentStep(processingSteps.length - 1);
        setScanResults(result);
        setTimeout(() => {
          if (isActive) {
            setAppState("results");
          }
        }, 300);
      } catch (error) {
        if (!isActive) {
          return;
        }

        const errorMessage = error instanceof Error ? error.message : "Failed to process prescription";

        if (errorMessage.includes("400") || errorMessage.includes("invalid")) {
          toast.error("Invalid image file. Please upload a valid prescription image.");
        } else if (errorMessage.includes("503") || errorMessage.includes("model")) {
          toast.error("Model not loaded. Please wait and try again.");
        } else if (errorMessage.includes("500")) {
          toast.error("Processing failed. Please try again.");
        } else {
          toast.error("Cannot connect to server. Please ensure the backend is running.");
        }

        setScanError(errorMessage);
        setAppState("error");
      } finally {
        if (progressTimer) {
          clearInterval(progressTimer);
        }
      }
    };

    processScan();

    return () => {
      isActive = false;
      if (progressTimer) {
        clearInterval(progressTimer);
      }
    };
  }, [appState, selectedFile]);

  const handleLoadModel = async () => {
    setIsLoadingModel(true);
    try {
      const result = await loadModel();
      if (result.success) {
        setIsModelLoaded(true);
        toast.success("Model loaded successfully!");
      } else {
        toast.error("Failed to load model. Please try again.");
      }
    } catch (error) {
      toast.error("Failed to load model. Please check the backend logs.");
      console.error("Model load error:", error);
    } finally {
      setIsLoadingModel(false);
    }
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      if (!isModelLoaded) {
        toast.error("Please load the model first before scanning.");
        return;
      }

      setSelectedFile(file);
      setScanResults(null);
      setScanError(null);
      setProgress(0);
      setCurrentStep(0);

      const reader = new FileReader();
      reader.onloadend = () => {
        setImagePreview(reader.result as string);
        setAppState("processing");
      };
      reader.readAsDataURL(file);
    }

    event.target.value = "";
  };

  const handleScanAnother = () => {
    setAppState("upload");
    setImagePreview("");
    setSelectedFile(null);
    setScanResults(null);
    setScanError(null);
    setProgress(0);
    setCurrentStep(0);
  };

  if (appState === "upload") {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center p-4">
        <Card className="w-full max-w-2xl p-8 md:p-12 border shadow-sm">
          <div className="text-center space-y-6">
            <div className="inline-flex p-4 rounded-2xl bg-muted mb-4">
              {isCheckingHealth ? (
                <Loader2 className="w-12 h-12 text-primary animate-spin" />
              ) : (
                <Scan className="w-12 h-12 text-primary" />
              )}
            </div>

            <div>
              <h1 className="text-4xl md:text-5xl font-bold text-foreground mb-3">
                Prescription Scanner
              </h1>
              <p className="text-muted-foreground text-lg">
                Upload or capture your medical prescription to extract medication information instantly
              </p>
            </div>

            {!configValid && !isCheckingHealth && (
              <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-4 flex items-start gap-3">
                <AlertCircle className="w-5 h-5 text-destructive flex-shrink-0 mt-0.5" />
                <div className="text-left flex-1">
                  <p className="text-sm font-semibold text-destructive mb-1">Configuration Error</p>
                  <p className="text-sm text-destructive/90 mb-2">
                    Backend API URL is not configured. Please set the <code className="bg-destructive/10 px-1 py-0.5 rounded text-xs">VITE_API_BASE_URL</code> environment variable.
                  </p>
                  <p className="text-xs text-destructive/80">
                    Current API URL: <code className="bg-destructive/10 px-1 py-0.5 rounded">{config.apiBaseUrl || "(not set)"}</code>
                  </p>
                </div>
              </div>
            )}

            {configValid && !isModelLoaded && !isCheckingHealth && (
              <div className="bg-accent/10 border border-accent/20 rounded-lg p-4 flex items-start gap-3">
                <AlertCircle className="w-5 h-5 text-accent flex-shrink-0 mt-0.5" />
                <div className="text-left flex-1">
                  <p className="text-sm font-semibold text-accent mb-1">Model Not Loaded</p>
                  <p className="text-sm text-accent/90 mb-3">
                    The AI model needs to be loaded before you can scan prescriptions.
                  </p>
                  <Button
                    onClick={handleLoadModel}
                    disabled={isLoadingModel}
                    size="sm"
                    className="bg-accent hover:bg-accent/90"
                  >
                    {isLoadingModel ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Loading Model...
                      </>
                    ) : (
                      "Load Model"
                    )}
                  </Button>
                </div>
              </div>
            )}

            <div className="grid gap-4 pt-8">
              <label htmlFor="file-upload" className={!isModelLoaded || isCheckingHealth || !configValid ? "cursor-not-allowed" : "cursor-pointer"}>
                <input
                  id="file-upload"
                  type="file"
                  accept="image/*"
                  onChange={handleFileChange}
                  className="hidden"
                  disabled={!isModelLoaded || isCheckingHealth || !configValid}
                />
                <Button
                  size="lg"
                  className="w-full h-14 text-base"
                  disabled={!isModelLoaded || isCheckingHealth || !configValid}
                  asChild
                >
                  <span>
                    <Upload className="mr-2 h-5 w-5" />
                    Upload Prescription Image
                  </span>
                </Button>
              </label>

              <label htmlFor="camera-capture" className={!isModelLoaded || isCheckingHealth || !configValid ? "cursor-not-allowed" : "cursor-pointer"}>
                <input
                  id="camera-capture"
                  type="file"
                  accept="image/*"
                  capture="environment"
                  onChange={handleFileChange}
                  className="hidden"
                  disabled={!isModelLoaded || isCheckingHealth || !configValid}
                />
                <Button
                  variant="secondary"
                  size="lg"
                  className="w-full h-14 text-base"
                  disabled={!isModelLoaded || isCheckingHealth || !configValid}
                  asChild
                >
                  <span>
                    <Camera className="mr-2 h-5 w-5" />
                    Capture with Camera
                  </span>
                </Button>
              </label>
            </div>

            <div className="pt-6 border-t border-border mt-8">
              <p className="text-sm text-muted-foreground">
                Supported formats: JPG, PNG, HEIC | Maximum file size: 10MB
              </p>
            </div>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background p-4 md:p-6">
      <div className="mx-auto max-w-7xl h-[calc(100vh-2rem)] md:h-[calc(100vh-3rem)]">
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25, ease: "easeOut" }}
          className="grid h-full gap-4 lg:grid-cols-[1.15fr_0.85fr]"
        >
          <Card className="p-4 md:p-5 border shadow-sm overflow-hidden">
            <div className="flex h-full flex-col gap-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <ImageIcon className="h-4 w-4 text-primary" />
                  <h2 className="text-sm font-semibold text-foreground">Image Preview</h2>
                </div>
                <Button variant="outline" size="sm" onClick={handleScanAnother}>
                  Scan Another
                </Button>
              </div>
              <div className="flex-1 rounded-lg border bg-muted/30 overflow-hidden">
                {imagePreview ? (
                  <img
                    src={imagePreview}
                    alt="Prescription preview"
                    className="h-full w-full object-contain"
                  />
                ) : (
                  <div className="h-full w-full grid place-items-center text-sm text-muted-foreground">
                    No image selected.
                  </div>
                )}
              </div>
            </div>
          </Card>

          <Card className="p-4 md:p-5 border shadow-sm overflow-y-auto">
            <AnimatePresence mode="wait">
              {appState === "processing" && (
                <motion.div
                  key="processing"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.2 }}
                >
                  <ProcessingScreen
                    progress={progress}
                    currentStep={currentStep}
                    steps={processingSteps}
                  />
                </motion.div>
              )}

              {appState === "results" && scanResults && (
                <motion.div
                  key="results"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.2 }}
                >
                  <ResultsScreen
                    onScanAnother={handleScanAnother}
                    scanResults={scanResults}
                  />
                </motion.div>
              )}

              {appState === "error" && (
                <motion.div
                  key="error"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.2 }}
                  className="space-y-4"
                >
                  <h2 className="text-xl font-semibold">Scan Failed</h2>
                  <p className="text-sm text-muted-foreground">
                    {scanError ?? "An unexpected error occurred while processing this prescription."}
                  </p>
                  <div className="flex gap-3">
                    <Button
                      onClick={() => {
                        if (selectedFile) {
                          setProgress(0);
                          setCurrentStep(0);
                          setScanError(null);
                          setAppState("processing");
                        }
                      }}
                      disabled={!selectedFile}
                    >
                      Retry
                    </Button>
                    <Button variant="outline" onClick={handleScanAnother}>
                      Scan Another
                    </Button>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </Card>
        </motion.div>
      </div>
    </div>
  );
};

export default Index;
