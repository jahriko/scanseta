import { CheckCircle2, Scan, Pill, FileText, AlertCircle, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { useState } from "react";
import { PrescriptionResponse, Medication } from "@/lib/prescription-api";

const derivePossibleMedications = (rawText?: string): Medication[] => {
  if (!rawText) {
    return [];
  }

  const tokens = rawText
    .split(/[\n,;+]+/)
    .map((token) => token.trim())
    .filter((token) => token.length > 0)
    .filter((token) => /[a-zA-Z]/.test(token));

  const uniqueTokens = Array.from(new Set(tokens));

  return uniqueTokens.map((name) => ({
    name,
    dosage: "",
    frequency: "",
    confidence: 0.5,
  }));
};

interface ResultsScreenProps {
  onScanAnother: () => void;
  imagePreview: string;
  scanResults: PrescriptionResponse;
}

const ResultsScreen = ({ onScanAnother, imagePreview, scanResults }: ResultsScreenProps) => {
  const [isRawTextOpen, setIsRawTextOpen] = useState(false);

  const filteredMedications = scanResults.medications.filter((medication) => {
    const normalizedName = medication.name?.trim().toLowerCase() ?? "";
    const isPlaceholderMedication = normalizedName === "unable to parse medications";
    const hasMeaningfulName = normalizedName.length > 0 && !isPlaceholderMedication;
    return hasMeaningfulName;
  });

  const fallbackMedications = filteredMedications.length === 0 ? derivePossibleMedications(scanResults.raw_text) : [];
  const medicationsToDisplay = filteredMedications.length > 0 ? filteredMedications : fallbackMedications;
  const isUsingFallbackMedications = filteredMedications.length === 0 && fallbackMedications.length > 0;

  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-background to-primary/5 p-4 py-8">
      <div className="max-w-5xl mx-auto space-y-8">
        <div className="text-center space-y-4 mb-10">
          <div className="inline-flex p-5 rounded-3xl bg-gradient-to-br from-green-500/20 to-emerald-500/10 shadow-lg mb-3">
            <CheckCircle2 className="w-12 h-12 text-green-600" />
          </div>
          <h2 className="text-4xl md:text-5xl font-bold text-foreground bg-gradient-to-r from-foreground to-foreground/70 bg-clip-text">
            Analysis Complete
          </h2>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
            Your prescription has been successfully processed
          </p>
        </div>

        <div className="grid md:grid-cols-2 gap-6">
          {imagePreview && (
            <Card className="p-5 shadow-xl border-2 hover:shadow-2xl transition-shadow">
              <div className="flex items-center gap-3 mb-4">
                <div className="p-2 rounded-lg bg-primary/10">
                  <FileText className="w-5 h-5 text-primary" />
                </div>
                <span className="font-semibold text-foreground text-lg">Original Prescription</span>
              </div>
              <div className="rounded-xl overflow-hidden border-2 border-border bg-muted/30 shadow-inner">
                <img 
                  src={imagePreview} 
                  alt="Original prescription" 
                  className="w-full max-h-[400px] object-contain"
                />
              </div>
            </Card>
          )}

          <Card className="p-5 shadow-xl border-2 hover:shadow-2xl transition-shadow flex flex-col justify-between">
            <div>
              <div className="flex items-center gap-3 mb-4">
                <div className="p-2 rounded-lg bg-accent/10">
                  <Clock className="w-5 h-5 text-accent" />
                </div>
                <span className="font-semibold text-foreground text-lg">Processing Summary</span>
              </div>
              <div className="space-y-4">
                <div className="flex items-center justify-between p-4 rounded-lg bg-muted/50">
                  <span className="text-sm font-medium text-muted-foreground">Processing Time</span>
                  <span className="text-lg font-bold text-foreground">{scanResults.processing_time.toFixed(2)}s</span>
                </div>
                <div className="flex items-center justify-between p-4 rounded-lg bg-muted/50">
                  <span className="text-sm font-medium text-muted-foreground">Medications Found</span>
                  <span className="text-lg font-bold text-foreground">{medicationsToDisplay.length}</span>
                </div>
                <div className="flex items-center justify-between p-4 rounded-lg bg-muted/50">
                  <span className="text-sm font-medium text-muted-foreground">Status</span>
                  <Badge className="bg-green-500/10 text-green-700 border-green-500/20">Success</Badge>
                </div>
              </div>
            </div>
          </Card>
        </div>

        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-primary/10">
                <Pill className="w-6 h-6 text-primary" />
              </div>
              <h3 className="text-2xl font-bold text-foreground">Medications</h3>
            </div>
            <Badge className="text-base px-4 py-2 bg-primary text-primary-foreground shadow-md">
              {medicationsToDisplay.length} {medicationsToDisplay.length === 1 ? 'item' : 'items'}
            </Badge>
          </div>

          {medicationsToDisplay.length === 0 ? (
            <Card className="p-12 shadow-xl border-2 text-center">
              <AlertCircle className="w-16 h-16 text-muted-foreground mx-auto mb-4 opacity-50" />
              <p className="text-lg font-medium text-muted-foreground mb-2">No medications detected</p>
              {scanResults.raw_text && (
                <p className="text-sm text-muted-foreground/70">
                  Review the extracted text below to confirm the prescription details.
                </p>
              )}
            </Card>
          ) : (
            <div className="grid gap-4">
              {medicationsToDisplay.map((med, index) => (
                <Card key={index} className="p-6 shadow-xl border-2 hover:shadow-2xl hover:border-primary/30 transition-all group">
                  <div className="flex items-start gap-4">
                    <div className="p-3 rounded-xl bg-gradient-to-br from-primary/10 to-accent/10 group-hover:from-primary/20 group-hover:to-accent/20 transition-colors">
                      <Pill className="w-6 h-6 text-primary" />
                    </div>
                    <div className="flex-1 space-y-3">
                      <h4 className="text-2xl font-bold text-foreground group-hover:text-primary transition-colors">
                        {med.name}
                      </h4>
                      {(med.dosage || med.frequency) && (
                        <div className="flex flex-wrap gap-2">
                          {med.dosage && (
                            <Badge variant="secondary" className="text-sm px-3 py-1 bg-muted hover:bg-muted/80">
                              <span className="font-semibold">Dosage:</span> {med.dosage}
                            </Badge>
                          )}
                          {med.frequency && (
                            <Badge variant="secondary" className="text-sm px-3 py-1 bg-muted hover:bg-muted/80">
                              <span className="font-semibold">Frequency:</span> {med.frequency}
                            </Badge>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </div>

        {scanResults.raw_text && (
          <Card className="p-5 shadow-xl border-2 hover:shadow-2xl transition-shadow">
            <Collapsible open={isRawTextOpen} onOpenChange={setIsRawTextOpen}>
              <CollapsibleTrigger className="flex items-center justify-between w-full hover:opacity-80 transition-opacity">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-primary/10">
                    <FileText className="w-5 h-5 text-primary" />
                  </div>
                  <span className="font-semibold text-foreground text-lg">Raw Extracted Text</span>
                </div>
                <Button variant="ghost" size="sm" className="hover:bg-primary/10">
                  {isRawTextOpen ? "Hide" : "Show"}
                </Button>
              </CollapsibleTrigger>
              <CollapsibleContent className="mt-5">
                <div className="bg-muted/50 rounded-xl p-5 border-2 border-border shadow-inner">
                  <pre className="text-sm text-foreground whitespace-pre-wrap font-mono leading-relaxed">
                    {scanResults.raw_text}
                  </pre>
                </div>
              </CollapsibleContent>
            </Collapsible>
          </Card>
        )}

        <div className="flex flex-col sm:flex-row gap-4 pt-6">
          <Button
            size="lg"
            onClick={onScanAnother}
            className="flex-1 h-16 text-lg font-semibold bg-gradient-to-r from-primary via-primary to-accent hover:from-primary/90 hover:via-primary/90 hover:to-accent/90 transition-all shadow-xl hover:shadow-2xl hover:scale-[1.02]"
          >
            <Scan className="mr-2 h-6 w-6" />
            Scan Another Prescription
          </Button>
        </div>
      </div>
    </div>
  );
};

export default ResultsScreen;
