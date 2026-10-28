import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Camera, Upload, Loader2, AlertCircle, Plus, ChevronRight, ImageUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import StatusGlyph, { GlyphState } from "@/components/StatusGlyph";
import { toast } from "sonner";
import ProcessingScreen from "@/components/ProcessingScreen";
import ResultsScreen from "@/components/ResultsScreen";
import { getEnrichmentJobStatus, getHealth, loadModel, PrescriptionResponse, scanPrescription } from "@/lib/prescription-api";
import { config, validateConfig } from "@/lib/config";
import { DEMO_DURATION_MS, demoPrescriptions, simulatePrescription } from "@/lib/demo-prescriptions";

type AppState = "upload" | "processing" | "results" | "error";
type ScanMode = "demo" | "live";

const processingSteps = [
  { label: "Uploading image to server", duration: 500 },
  { label: "Analyzing image with AI model", duration: 1500 },
  { label: "Extracting medication information", duration: 1000 },
  { label: "Finalizing scan response", duration: 500 },
];

const terminalEnrichmentStatuses = new Set(["completed", "partial", "failed", "timed_out", "expired", "not_requested", "disabled"]);
const demoProcessingSteps = [
  { label: "Matching the sample image", duration: DEMO_DURATION_MS / 4 },
  { label: "Replaying the prepared transcription", duration: DEMO_DURATION_MS / 4 },
  { label: "Adding review notes", duration: DEMO_DURATION_MS / 4 },
  { label: "Preparing simulated results", duration: DEMO_DURATION_MS / 4 },
];

const normalizeStatus = (value?: string | null): string => (value ?? "").trim().toLowerCase();

const getRightPanelMeta = (
  appState: AppState,
  scanResults: PrescriptionResponse | null,
  isDemo: boolean,
): { title: string; subtitle: string; statusLabel: string; statusClassName: string } => {
  if (isDemo) {
    return {
      title: appState === "processing" ? "Scanning prescription" : appState === "error" ? "Sample not supported" : "Medication Review",
      subtitle: appState === "processing" ? "Reading the prescription image." : appState === "error" ? "Choose one of the sample prescriptions." : "Extracted from the prescription image.",
      statusLabel: appState === "processing" ? "Processing" : appState === "error" ? "Error" : "Complete",
      statusClassName: appState === "processing" ? "border-blue-500/30 bg-blue-500/10 text-blue-700" : appState === "error" ? "border-destructive/30 bg-destructive/10 text-destructive" : "border-green-500/30 bg-green-500/10 text-green-700",
    };
  }
  if (appState === "processing") {
    return {
      title: "Live Analysis",
      subtitle: "OCR extraction runs first, then source validation continues.",
      statusLabel: "Processing",
      statusClassName: "border-blue-500/30 bg-blue-500/10 text-blue-700",
    };
  }

  if (appState === "error") {
    return {
      title: "Analysis Interrupted",
      subtitle: "The scan did not complete. Retry or scan another prescription.",
      statusLabel: "Error",
      statusClassName: "border-destructive/30 bg-destructive/10 text-destructive",
    };
  }

  if (appState === "results") {
    const enrichmentStatus = normalizeStatus(scanResults?.enrichment_status);

    if (!scanResults?.can_enrich || enrichmentStatus === "not_requested") {
      return {
        title: "Medication Review",
        subtitle: "Structured OCR extraction is available for this scan.",
        statusLabel: "Complete",
        statusClassName: "border-green-500/30 bg-green-500/10 text-green-700",
      };
    }

    if (enrichmentStatus === "disabled") {
      return {
        title: "Medication Review",
        subtitle: scanResults?.enrichment_message || "Live FDA and PNDF validation is disabled on this server.",
        statusLabel: "OCR Only",
        statusClassName: "border-muted bg-muted/40 text-muted-foreground",
      };
    }

    if (enrichmentStatus === "queued" || enrichmentStatus === "running") {
      return {
        title: "Medication Review",
        subtitle: "Results are live. FDA and PNDF validation is still in progress.",
        statusLabel: "Validation Running",
        statusClassName: "border-blue-500/30 bg-blue-500/10 text-blue-700",
      };
    }

    if (enrichmentStatus === "partial") {
      return {
        title: "Medication Review",
        subtitle: "One source completed while another source timed out or failed.",
        statusLabel: "Partially Complete",
        statusClassName: "border-amber-500/30 bg-amber-500/10 text-amber-700",
      };
    }

    if (enrichmentStatus === "timed_out" || enrichmentStatus === "expired") {
      return {
        title: "Medication Review",
        subtitle: "Validation timed out before all source checks finished.",
        statusLabel: "Timed Out",
        statusClassName: "border-amber-500/30 bg-amber-500/10 text-amber-700",
      };
    }

    if (enrichmentStatus === "failed") {
      return {
        title: "Medication Review",
        subtitle: "Drug verification could not be completed due to a network or source error.",
        statusLabel: "Verification Failed",
        statusClassName: "border-destructive/30 bg-destructive/10 text-destructive",
      };
    }

    return {
      title: "Medication Review",
      subtitle: "OCR and validation results are ready to inspect.",
      statusLabel: "Complete",
      statusClassName: "border-green-500/30 bg-green-500/10 text-green-700",
    };
  }

  return {
    title: "Analysis Workspace",
    subtitle: "Upload a prescription image to begin analysis.",
    statusLabel: "Ready",
    statusClassName: "border-muted bg-muted/60 text-muted-foreground",
  };
};

const statusGlyph = (statusLabel: string): GlyphState => {
  switch (statusLabel) {
    case "Processing":
      return "progress";
    case "Complete":
      return "done";
    case "Validation Running":
      return "pending";
    case "Partially Complete":
    case "Timed Out":
      return "review";
    case "Error":
    case "Verification Failed":
      return "missing";
    default:
      return "todo";
  }
};

const BrandMark = () => (
  <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true" className="shrink-0">
    <rect width="22" height="22" rx="6" fill="hsl(var(--sidebar-primary))" />
    <path d="M6 7.5h6.5M6 11h10M6 14.5h7.5" stroke="hsl(var(--sidebar-primary-foreground))" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);

const ModeSwitch = ({ mode, onModeChange }: { mode: ScanMode; onModeChange: (mode: ScanMode) => void }) => (
  <div role="group" aria-label="Scan mode" className="grid grid-cols-2 rounded-md bg-sidebar-accent p-0.5">
    {(["demo", "live"] as const).map((value) => (
      <button
        key={value}
        type="button"
        aria-pressed={mode === value}
        onClick={() => onModeChange(value)}
        className={`h-7 rounded-[5px] px-3 text-xs font-medium transition-colors duration-150 focus-visible:outline-sidebar-ring ${
          mode === value
            ? "bg-sidebar-foreground/15 text-sidebar-accent-foreground shadow-[0_1px_2px_rgba(0,0,0,0.3)]"
            : "text-sidebar-foreground hover:text-sidebar-accent-foreground"
        }`}
      >
        {value === "demo" ? "Demo mode" : "Live mode"}
      </button>
    ))}
  </div>
);

const Index = () => {
  const [scanMode, setScanMode] = useState<ScanMode>(config.defaultScanMode);
  const isDemo = scanMode === "demo";
  const activeProcessingSteps = isDemo ? demoProcessingSteps : processingSteps;
  const [appState, setAppState] = useState<AppState>("upload");
  const [imagePreview, setImagePreview] = useState<string>("");
  const [previewObjectUrl, setPreviewObjectUrl] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [scanResults, setScanResults] = useState<PrescriptionResponse | null>(null);
  const [isModelLoaded, setIsModelLoaded] = useState<boolean>(false);
  const [isLoadingModel, setIsLoadingModel] = useState<boolean>(false);
  const [isCheckingHealth, setIsCheckingHealth] = useState<boolean>(!isDemo);
  const [configValid, setConfigValid] = useState<boolean>(true);
  const [scanError, setScanError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [currentStep, setCurrentStep] = useState(0);
  const [isSelectingDemo, setIsSelectingDemo] = useState(false);
  const [isCameraOpen, setIsCameraOpen] = useState(false);
  const [isStartingCamera, setIsStartingCamera] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const cameraInputRef = useRef<HTMLInputElement | null>(null);
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const [imageRatio, setImageRatio] = useState<number | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const cameraStreamRef = useRef<MediaStream | null>(null);
  const selectionVersion = useRef(0);
  const canScan = isDemo || (isModelLoaded && configValid && !isCheckingHealth);

  const resetScanState = () => {
    setScanResults(null);
    setScanError(null);
    setProgress(0);
    setCurrentStep(0);
  };

  const resetPreview = () => {
    setImagePreview("");
    setImageRatio(null);
    setPreviewObjectUrl((previousUrl) => {
      if (previousUrl) {
        URL.revokeObjectURL(previousUrl);
      }
      return null;
    });
  };

  const stopCameraStream = () => {
    if (cameraStreamRef.current) {
      cameraStreamRef.current.getTracks().forEach((track) => track.stop());
      cameraStreamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  };

  const closeCameraCapture = () => {
    setIsCameraOpen(false);
    setCameraError(null);
    stopCameraStream();
  };

  const queueFileForScan = (file: File) => {
    if (!canScan) {
      toast.error("Please load the model first before scanning.");
      return;
    }

    const version = ++selectionVersion.current;
    resetPreview();
    setSelectedFile(file);
    resetScanState();

    const reader = new FileReader();
    reader.onloadend = () => {
      if (version !== selectionVersion.current) return;
      setImagePreview(reader.result as string);
      setAppState("processing");
    };
    reader.readAsDataURL(file);
  };

  useEffect(() => {
    return () => {
      if (previewObjectUrl) {
        URL.revokeObjectURL(previewObjectUrl);
      }
    };
  }, [previewObjectUrl]);

  useEffect(() => {
    return () => {
      if (cameraStreamRef.current) {
        cameraStreamRef.current.getTracks().forEach((track) => track.stop());
        cameraStreamRef.current = null;
      }
      if (videoRef.current) {
        videoRef.current.srcObject = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!isCameraOpen || !cameraStreamRef.current || !videoRef.current) {
      return;
    }

    const videoElement = videoRef.current;
    videoElement.srcObject = cameraStreamRef.current;
    void videoElement.play().catch(() => {
      // Ignore autoplay failures on strict browsers; controls remain available.
    });
  }, [isCameraOpen]);

  useEffect(() => {
    if (appState !== "upload" && isCameraOpen) {
      setIsCameraOpen(false);
      setCameraError(null);
      if (cameraStreamRef.current) {
        cameraStreamRef.current.getTracks().forEach((track) => track.stop());
        cameraStreamRef.current = null;
      }
      if (videoRef.current) {
        videoRef.current.srcObject = null;
      }
    }
  }, [appState, isCameraOpen]);

  useEffect(() => {
    if (isDemo) {
      setIsCheckingHealth(false);
      setConfigValid(true);
      return;
    }
    let isActive = true;
    const checkHealth = async () => {
      setIsCheckingHealth(true);
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
        if (!isActive) return;
        setIsModelLoaded(health.model_loaded);
      } catch (error) {
        if (!isActive) return;
        const errorMessage = error instanceof Error ? error.message : "Cannot connect to server. Please ensure the backend is running.";
        toast.error(errorMessage);
        console.error("Health check error:", error);
      } finally {
        if (isActive) setIsCheckingHealth(false);
      }
    };

    checkHealth();
    return () => { isActive = false; };
  }, [isDemo]);

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
        const totalDuration = activeProcessingSteps.reduce((sum, step) => sum + step.duration, 0);
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

          const stepThreshold = ((stepIndex + 1) / activeProcessingSteps.length) * 100;
          if (currentProgress >= stepThreshold && stepIndex < activeProcessingSteps.length - 1) {
            stepIndex++;
            setCurrentStep(stepIndex);
          }
        }, interval);

        const result = isDemo ? await simulatePrescription(selectedFile) : await scanPrescription(selectedFile);

        if (!isActive) {
          return;
        }

        if (progressTimer) {
          clearInterval(progressTimer);
        }

        setProgress(100);
        setCurrentStep(activeProcessingSteps.length - 1);
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

        if (isDemo) {
          toast.error(errorMessage);
        } else if (errorMessage.includes("400") || errorMessage.includes("invalid")) {
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
  }, [appState, selectedFile, isDemo, activeProcessingSteps]);

  useEffect(() => {
    if (isDemo || !scanResults?.enrichment_job_id) {
      return;
    }

    const currentStatus = (scanResults.enrichment_status ?? "").toLowerCase();
    if (!currentStatus || terminalEnrichmentStatuses.has(currentStatus)) {
      return;
    }

    const jobId = scanResults.enrichment_job_id;
    let isActive = true;
    let isPollInFlight = false;
    let pollAttempts = 0;
    // Backend enrichment can take up to ~75s, so allow enough polls before
    // concluding a client-side timeout.
    const maxPollAttempts = 120;

    const pollStatus = async () => {
      if (!isActive || !jobId || isPollInFlight) {
        return;
      }

      isPollInFlight = true;
      pollAttempts += 1;
      try {
        const status = await getEnrichmentJobStatus(jobId);
        if (!isActive) {
          return;
        }

        setScanResults((previous) => {
          if (!previous || previous.enrichment_job_id !== status.job_id) {
            return previous;
          }

          return {
            ...previous,
            enrichment_status: status.status,
            fda_enrichment_status: status.fda_status,
            pndf_enrichment_status: status.pndf_status,
            enrichment_updated_at: status.updated_at ?? previous.enrichment_updated_at ?? null,
            fda_verification: status.fda_verification,
            pndf_enriched: status.pndf_enriched,
            enriched: status.pndf_enriched,
            enriched_medications: status.pndf_enriched,
            enrichment_message: status.message ?? previous.enrichment_message ?? null,
          };
        });

        const normalizedStatus = (status.status ?? "").toLowerCase();
        if (terminalEnrichmentStatuses.has(normalizedStatus) && pollTimer) {
          clearInterval(pollTimer);
        }
      } catch (error) {
        if (!isActive) {
          return;
        }
        if (pollAttempts >= maxPollAttempts && pollTimer) {
          clearInterval(pollTimer);
        }
      } finally {
        isPollInFlight = false;
      }

      if (pollAttempts >= maxPollAttempts && pollTimer) {
        clearInterval(pollTimer);
        setScanResults((previous) => {
          if (!previous) {
            return previous;
          }
          const previousStatus = normalizeStatus(previous.enrichment_status);
          if (terminalEnrichmentStatuses.has(previousStatus)) {
            return previous;
          }
          return {
            ...previous,
            enrichment_status: "timed_out",
            enrichment_updated_at: previous.enrichment_updated_at ?? new Date().toISOString(),
          };
        });
      }
    };

    const pollTimer = setInterval(pollStatus, 1000);
    void pollStatus();

    return () => {
      isActive = false;
      if (pollTimer) {
        clearInterval(pollTimer);
      }
    };
  }, [
    isDemo,
    scanResults?.enrichment_job_id,
    scanResults?.enrichment_status,
  ]);

  const handleLoadModel = async () => {
    const version = selectionVersion.current;
    setIsLoadingModel(true);
    try {
      const result = await loadModel();
      if (version !== selectionVersion.current) return;
      if (result.success) {
        setIsModelLoaded(true);
        toast.success("Model loaded successfully!");
      } else {
        toast.error("Failed to load model. Please try again.");
      }
    } catch (error) {
      if (version !== selectionVersion.current) return;
      toast.error("Failed to load model. Please check the backend logs.");
      console.error("Model load error:", error);
    } finally {
      if (version === selectionVersion.current) setIsLoadingModel(false);
    }
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      queueFileForScan(file);
    }

    event.target.value = "";
  };

  const handleOpenCameraCapture = async () => {
    if (isDemo) return;
    if (!isModelLoaded) {
      toast.error("Please load the model first before scanning.");
      return;
    }

    if (!configValid || isCheckingHealth || isStartingCamera) {
      return;
    }

    setCameraError(null);

    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      cameraInputRef.current?.click();
      return;
    }

    setIsStartingCamera(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false,
      });
      cameraStreamRef.current = stream;
      setIsCameraOpen(true);
    } catch (error) {
      console.error("Camera access error:", error);
      setCameraError("Camera access was denied. Falling back to file picker.");
      toast.error("Unable to open camera. Please allow permission or choose an image.");
      cameraInputRef.current?.click();
    } finally {
      setIsStartingCamera(false);
    }
  };

  const handleCameraPhotoCapture = async () => {
    const videoElement = videoRef.current;
    if (!videoElement) {
      return;
    }

    const { videoWidth, videoHeight } = videoElement;
    if (!videoWidth || !videoHeight) {
      toast.error("Camera is still initializing. Please try again.");
      return;
    }

    const canvas = document.createElement("canvas");
    canvas.width = videoWidth;
    canvas.height = videoHeight;

    const context = canvas.getContext("2d");
    if (!context) {
      toast.error("Could not capture image from camera.");
      return;
    }

    context.drawImage(videoElement, 0, 0, videoWidth, videoHeight);

    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob(resolve, "image/jpeg", 0.92);
    });

    if (!blob) {
      toast.error("Could not generate camera image.");
      return;
    }

    const file = new File([blob], `camera-capture-${Date.now()}.jpg`, { type: "image/jpeg" });
    closeCameraCapture();
    queueFileForScan(file);
  };

  const handleDemoImageSelect = async (fileName: string) => {
    if (!canScan) {
      toast.error("Please load the model first before scanning.");
      return;
    }
    if (!isDemo && (!configValid || isCheckingHealth)) {
      return;
    }

    setIsSelectingDemo(true);
    const version = ++selectionVersion.current;
    try {
      const response = await fetch(`/demo-prescriptions/${fileName}`);
      if (!response.ok) {
        throw new Error(`Failed to load demo image (${response.status})`);
      }

      const blob = await response.blob();
      if (version !== selectionVersion.current) return;
      const file = new File([blob], fileName, { type: blob.type || "image/jpeg" });
      const objectUrl = URL.createObjectURL(blob);

      resetPreview();
      setPreviewObjectUrl(objectUrl);
      setImagePreview(objectUrl);
      setSelectedFile(file);
      resetScanState();
      setAppState("processing");
    } catch (error) {
      if (version !== selectionVersion.current) return;
      const errorMessage = error instanceof Error ? error.message : "Could not load demo image.";
      toast.error(errorMessage);
    } finally {
      if (version === selectionVersion.current) setIsSelectingDemo(false);
    }
  };

  const handleScanAnother = () => {
    selectionVersion.current += 1;
    setIsSelectingDemo(false);
    setAppState("upload");
    resetPreview();
    setSelectedFile(null);
    resetScanState();
  };

  const handleModeChange = (mode: ScanMode) => {
    if (mode === scanMode) return;
    toast.dismiss();
    closeCameraCapture();
    handleScanAnother();
    setIsModelLoaded(false);
    setIsLoadingModel(false);
    setIsCheckingHealth(mode === "live");
    setScanMode(mode);
  };

  const rightPanelMeta = getRightPanelMeta(appState, scanResults, isDemo);
  const topStatus = appState === "upload"
    ? { label: isCheckingHealth ? "Connecting" : !isDemo && !isModelLoaded ? "Model not loaded" : "Ready", glyph: (isCheckingHealth ? "pending" : !isDemo && !isModelLoaded ? "review" : "done") as GlyphState }
    : { label: rightPanelMeta.statusLabel, glyph: statusGlyph(rightPanelMeta.statusLabel) };
  const backendStatus = isDemo
    ? "Prepared samples, no backend"
    : isCheckingHealth
      ? "Connecting to backend"
      : !configValid
        ? "Backend URL not set"
        : isModelLoaded
          ? "Model loaded"
          : "Model not loaded";
  const activeFileName = appState === "upload" ? null : selectedFile?.name ?? null;

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    const file = event.dataTransfer.files?.[0];
    if (file && file.type.startsWith("image/")) {
      queueFileForScan(file);
    }
  };

  const sampleButtons = (variant: "sidebar" | "grid") =>
    demoPrescriptions.map(({ fileName, medications }) => {
      const isActive = activeFileName === fileName;
      const summary = medications.map((m) => m.name.replace(/\s*\(.*\)$/, "")).join(", ");
      const common = {
        type: "button" as const,
        "aria-label": `Scan sample ${fileName}`,
        "aria-current": isActive ? ("true" as const) : undefined,
        onClick: () => handleDemoImageSelect(fileName),
        disabled: !canScan || isSelectingDemo,
      };
      return variant === "sidebar" ? (
        <li key={fileName}>
          <button
            {...common}
            className={`group flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-sidebar-ring ${
              isActive ? "bg-sidebar-accent text-sidebar-accent-foreground" : "hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
            }`}
          >
            <img src={`/demo-prescriptions/${fileName}`} alt="" loading="lazy" className="h-8 w-7 shrink-0 rounded-[3px] bg-sidebar-accent object-cover opacity-90" />
            <span className="min-w-0">
              <span className="block truncate font-mono text-xs">{fileName.replace(/\.(jpg|png)$/, "")}</span>
              <span className="block truncate text-[11px] text-sidebar-foreground/80">{summary}</span>
            </span>
          </button>
        </li>
      ) : (
        <button
          key={fileName}
          {...common}
          className="group overflow-hidden rounded-md border border-border bg-card text-left transition-shadow duration-150 hover:shadow-[0_2px_8px_hsl(228_20%_20%/0.08)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          <img src={`/demo-prescriptions/${fileName}`} alt="" loading="lazy" className="h-24 w-full bg-muted object-cover" />
          <span className="block truncate px-2.5 pt-2 font-mono text-xs text-foreground">{fileName.replace(/\.(jpg|png)$/, "")}</span>
          <span className="block truncate px-2.5 pb-2 text-[11px] text-muted-foreground">{summary}</span>
        </button>
      );
    });

  return (
    <div className="flex min-h-screen bg-background lg:h-screen lg:overflow-hidden">
      <aside className="hidden w-[248px] shrink-0 flex-col bg-sidebar text-sidebar-foreground lg:flex">
        <div className="flex h-12 items-center gap-2.5 px-4">
          <BrandMark />
          <h1 className="text-sm font-semibold tracking-[-0.01em] text-sidebar-accent-foreground">Scanseta</h1>
        </div>
        <div className="px-2">
          <button
            type="button"
            onClick={handleScanAnother}
            className="flex h-8 w-full items-center gap-2 rounded-md px-2 text-[13px] text-sidebar-accent-foreground transition-colors duration-150 hover:bg-sidebar-accent focus-visible:outline-sidebar-ring"
          >
            <Plus className="h-4 w-4 text-sidebar-foreground" />
            New scan
          </button>
        </div>
        <p className="mt-5 px-4 pb-1.5 text-[11px] font-medium text-sidebar-foreground/80">Sample prescriptions</p>
        <ul className="min-h-0 flex-1 space-y-px overflow-y-auto px-2 pb-3">{sampleButtons("sidebar")}</ul>
        <div className="space-y-2.5 border-t border-sidebar-border p-3">
          <p className="flex items-center gap-2 px-1 text-[11px]">
            <span className={`h-1.5 w-1.5 rounded-full ${isDemo ? "bg-sidebar-foreground" : isModelLoaded ? "bg-sidebar-primary" : "bg-[hsl(var(--review))]"}`} />
            {backendStatus}
          </p>
          <ModeSwitch mode={scanMode} onModeChange={handleModeChange} />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center justify-between gap-3 bg-sidebar px-4 py-2.5 lg:hidden">
          <div className="flex items-center gap-2">
            <BrandMark />
            <h1 className="text-sm font-semibold text-sidebar-accent-foreground">Scanseta</h1>
          </div>
          <ModeSwitch mode={scanMode} onModeChange={handleModeChange} />
        </div>

        <header className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-border px-4 md:px-5">
          <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-[13px]">
            <span className="text-muted-foreground">Scans</span>
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
            <span className="truncate font-medium text-foreground">{activeFileName ?? "New scan"}</span>
            <span className="ml-2 hidden items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground sm:inline-flex">
              <StatusGlyph state={topStatus.glyph} fraction={progress / 100} size={12} />
              {topStatus.label}
            </span>
          </nav>
          {appState !== "upload" && appState !== "results" && (
            <Button variant="outline" size="sm" onClick={handleScanAnother} className="h-7 px-2.5 text-xs">
              Scan Another
            </Button>
          )}
        </header>

        {appState === "upload" ? (
          <main className="flex flex-1 flex-col overflow-y-auto lg:p-8">
            <div
              onDragOver={(event) => event.preventDefault()}
              onDrop={handleDrop}
              className="flex w-full flex-1 flex-col items-center justify-center px-5 py-12 text-center lg:rounded-xl lg:border lg:border-dashed lg:border-input lg:bg-canvas/50"
            >
              <div className="grid h-11 w-11 place-items-center rounded-lg bg-muted text-muted-foreground">
                {isCheckingHealth ? <Loader2 className="h-5 w-5 animate-spin" /> : <ImageUp className="h-5 w-5" />}
              </div>
              <h2 className="mt-4 text-lg font-semibold tracking-[-0.015em] text-foreground">Scan a prescription</h2>
              <p className="mt-1.5 max-w-sm text-balance text-sm leading-relaxed text-muted-foreground">
                {isDemo
                  ? "Pick a sample prescription, or drop one of the sample images here."
                  : "Upload or drop a photo of a handwritten prescription, or take one with the camera."}
              </p>

              {!isDemo && !configValid && !isCheckingHealth && (
                <div className="mt-6 flex w-full max-w-lg gap-3 rounded-md bg-destructive/5 px-4 py-3 text-left ring-1 ring-inset ring-destructive/20">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                  <div className="min-w-0 text-[13px]">
                    <p className="font-semibold text-foreground">Configuration Error</p>
                    <p className="mt-0.5 text-foreground/80">
                      The backend address is not set. Set <code className="font-mono text-xs">VITE_API_BASE_URL</code> and rebuild.
                    </p>
                    <p className="mt-1 truncate text-xs text-muted-foreground">
                      Current: <code className="font-mono">{config.apiBaseUrl || "(not set)"}</code>
                    </p>
                  </div>
                </div>
              )}

              {!isDemo && configValid && !isModelLoaded && !isCheckingHealth && (
                <div className="mt-6 flex w-full max-w-lg items-center gap-3 rounded-md bg-review-surface px-4 py-3 text-left ring-1 ring-inset ring-review/25">
                  <StatusGlyph state="review" />
                  <div className="min-w-0 flex-1 text-[13px]">
                    <p className="font-semibold text-foreground">Model Not Loaded</p>
                    <p className="mt-0.5 text-foreground/80">Load the AI model before scanning. This can take a few minutes.</p>
                  </div>
                  <Button onClick={handleLoadModel} disabled={isLoadingModel} size="sm">
                    {isLoadingModel ? (
                      <>
                        <Loader2 className="animate-spin" />
                        Loading
                      </>
                    ) : (
                      "Load Model"
                    )}
                  </Button>
                </div>
              )}

              <div className="mt-7 flex w-full flex-col gap-2.5 sm:flex-row sm:justify-center">
                <input id="file-upload" ref={uploadInputRef} type="file" accept="image/*" onChange={handleFileChange} className="hidden" disabled={!canScan} />
                <Button size="lg" disabled={!canScan} onClick={() => uploadInputRef.current?.click()}>
                  <Upload />
                  Upload Prescription Image
                </Button>
                <input
                  id="camera-capture"
                  ref={cameraInputRef}
                  type="file"
                  accept="image/*"
                  aria-label="Capture prescription image"
                  capture="environment"
                  onChange={handleFileChange}
                  className="hidden"
                  disabled={!canScan}
                />
                <Button variant="outline" size="lg" disabled={isDemo || !canScan || isStartingCamera} onClick={handleOpenCameraCapture}>
                  {isStartingCamera ? <Loader2 className="animate-spin" /> : <Camera />}
                  Capture with Camera
                </Button>
              </div>

              {cameraError && <p className="mt-3 text-xs text-review">{cameraError}</p>}
              {isCameraOpen && (
                <div className="mt-5 w-full max-w-lg space-y-3 rounded-lg border border-border bg-card p-3">
                  <video ref={videoRef} className="max-h-[50vh] w-full rounded-md bg-muted object-cover" playsInline muted autoPlay />
                  <div className="flex gap-2.5">
                    <Button className="flex-1" onClick={handleCameraPhotoCapture}>Take Photo</Button>
                    <Button variant="outline" className="flex-1" onClick={closeCameraCapture}>Cancel</Button>
                  </div>
                </div>
              )}

              <p className="mt-4 text-xs text-muted-foreground">
                {isDemo ? "Camera capture is available in Live mode." : "JPG, PNG or HEIC, up to 10 MB."}
              </p>
              {isSelectingDemo && (
                <p className="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Loading sample image
                </p>
              )}
            </div>

            <section className="border-t border-border px-4 py-6 lg:hidden" aria-label="Sample prescriptions">
              <h3 className="mb-3 text-[13px] font-medium text-foreground">Sample prescriptions</h3>
              <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">{sampleButtons("grid")}</div>
            </section>
          </main>
        ) : (
          <main className="grid min-h-0 flex-1 lg:grid-cols-[minmax(0,1fr)_440px]">
            <div className="relative min-h-[42vh] overflow-hidden bg-canvas lg:min-h-0">
              {imagePreview ? (
                <div className="absolute inset-0 grid place-items-center p-4 [container-type:size] md:p-6">
                  <div
                    className="relative max-h-full max-w-full"
                    style={imageRatio ? { aspectRatio: imageRatio, width: `min(100cqw, calc(100cqh * ${imageRatio}))` } : undefined}
                  >
                    <img
                      src={imagePreview}
                      alt="Prescription photo"
                      onLoad={(event) => setImageRatio(event.currentTarget.naturalWidth / event.currentTarget.naturalHeight || null)}
                      className="block h-full w-full object-contain"
                    />
                    {appState === "processing" && (
                      <div aria-hidden="true" className="pointer-events-none absolute inset-0">
                        <div
                          className="absolute inset-x-0 top-0 bg-primary/10 mix-blend-multiply transition-[height] duration-200 ease-linear"
                          style={{ height: `${progress}%` }}
                        />
                        <div
                          className="absolute inset-x-0 bottom-0 bg-canvas/70 backdrop-grayscale transition-[top] duration-200 ease-linear"
                          style={{ top: `${progress}%` }}
                        />
                        <div
                          className="absolute inset-x-0 h-[3px] -translate-y-1/2 bg-primary shadow-[0_0_0_1px_hsl(var(--primary)/0.2),0_0_24px_4px_hsl(var(--primary)/0.45)] transition-[top] duration-200 ease-linear"
                          style={{ top: `${progress}%` }}
                        />
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="grid h-full place-items-center text-sm text-muted-foreground">No image selected.</div>
              )}
            </div>

            <section className="flex min-h-0 flex-col border-t border-border lg:border-l lg:border-t-0">
              <div className="min-h-0 flex-1 overflow-y-auto pb-6">
                <AnimatePresence mode="wait">
                  {appState === "processing" && (
                    <motion.div key="processing" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }} className="p-5">
                      <ProcessingScreen progress={progress} currentStep={currentStep} steps={activeProcessingSteps} simulated={isDemo} />
                    </motion.div>
                  )}

                  {appState === "results" && scanResults && (
                    <motion.div key="results" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }}>
                      <div className="px-5 pb-2 pt-5">
                        <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-foreground">{rightPanelMeta.title}</h2>
                        <p className="mt-0.5 text-[13px] text-muted-foreground">{rightPanelMeta.subtitle}</p>
                      </div>
                      <ResultsScreen onScanAnother={handleScanAnother} scanResults={scanResults} />
                    </motion.div>
                  )}

                  {appState === "error" && (
                    <motion.div key="error" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }} className="p-5">
                      <div className="flex items-center gap-2">
                        <StatusGlyph state="missing" />
                        <h2 className="text-[15px] font-semibold text-foreground">Scan Failed</h2>
                      </div>
                      <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">
                        {scanError ?? "Something went wrong while reading this prescription."} {rightPanelMeta.subtitle}
                      </p>
                      <div className="mt-4 flex gap-2.5">
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
                        <Button variant="outline" onClick={handleScanAnother}>Scan Another</Button>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </section>
          </main>
        )}
      </div>
    </div>
  );
};

export default Index;
