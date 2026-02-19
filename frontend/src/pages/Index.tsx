import { useState, useEffect } from "react";
import { Camera, Upload, Scan, Loader2, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { toast } from "sonner";
import ProcessingScreen from "@/components/ProcessingScreen";
import ResultsScreen from "@/components/ResultsScreen";
import { getHealth, loadModel, PrescriptionResponse } from "@/lib/prescription-api";
import { config, validateConfig } from "@/lib/config";

type AppState = "upload" | "processing" | "results";

const Index = () => {
  const [appState, setAppState] = useState<AppState>("upload");
  const [imagePreview, setImagePreview] = useState<string>("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [scanResults, setScanResults] = useState<PrescriptionResponse | null>(null);
  const [isModelLoaded, setIsModelLoaded] = useState<boolean>(false);
  const [isLoadingModel, setIsLoadingModel] = useState<boolean>(false);
  const [isCheckingHealth, setIsCheckingHealth] = useState<boolean>(true);
  const [configValid, setConfigValid] = useState<boolean>(true);

  useEffect(() => {
    const checkHealth = async () => {
      // First validate configuration
      const validation = validateConfig();
      setConfigValid(validation.valid);
      
      if (!validation.valid) {
        validation.errors.forEach(error => {
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
      const reader = new FileReader();
      reader.onloadend = () => {
        setImagePreview(reader.result as string);
        setAppState("processing");
      };
      reader.readAsDataURL(file);
    }
  };

  const handleScanComplete = (results: PrescriptionResponse) => {
    setScanResults(results);
    setAppState("results");
  };

  const handleScanAnother = () => {
    setAppState("upload");
    setImagePreview("");
    setSelectedFile(null);
    setScanResults(null);
  };

  if (appState === "processing" && selectedFile) {
    return <ProcessingScreen onComplete={handleScanComplete} imagePreview={imagePreview} file={selectedFile} />;
  }

  if (appState === "results" && scanResults) {
    return <ResultsScreen onScanAnother={handleScanAnother} imagePreview={imagePreview} scanResults={scanResults} />;
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <Card className="w-full max-w-2xl p-8 md:p-12 shadow-[var(--card-shadow)]">
        <div className="text-center space-y-6">
          <div className="inline-flex p-4 rounded-2xl bg-gradient-to-br from-primary/10 to-accent/10 mb-4">
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
                  Current API URL: <code className="bg-destructive/10 px-1 py-0.5 rounded">{config.apiBaseUrl || '(not set)'}</code>
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
                className="w-full h-14 text-base bg-gradient-to-r from-primary to-primary/90 hover:from-primary/90 hover:to-primary/80 transition-all shadow-lg"
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
                className="w-full h-14 text-base transition-all"
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
              Supported formats: JPG, PNG, HEIC • Maximum file size: 10MB
            </p>
          </div>
        </div>
      </Card>
    </div>
  );
};

export default Index;
