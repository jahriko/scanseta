import { useState } from "react";
import { motion } from "framer-motion";
import {
  Scan,
  Pill,
  FileText,
  AlertCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  PrescriptionResponse,
  Medication,
} from "@/lib/prescription-api";

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
    confidence: 0.5,
  }));
};

const normalizeMedicationKey = (value?: string | null): string =>
  (value ?? "").trim().toLowerCase().replace(/\s+/g, " ");

const UPPERCASE_MEDICATION_TOKENS = new Set([
  "IV",
  "IM",
  "XR",
  "SR",
  "ER",
  "IR",
  "CR",
  "EC",
  "OD",
  "BD",
  "TID",
  "QID",
  "PRN",
  "PO",
]);

const LOWERCASE_UNIT_TOKENS = new Set(["mg", "mcg", "g", "ml", "kg"]);

const toDisplayMedicationName = (value?: string | null): string => {
  const normalizedValue = (value ?? "").trim().replace(/\s+/g, " ");
  if (!normalizedValue) {
    return "";
  }

  const formatToken = (token: string): string => {
    if (/^\d+$/.test(token)) {
      return token;
    }

    const upperToken = token.toUpperCase();
    const lowerToken = token.toLowerCase();

    if (UPPERCASE_MEDICATION_TOKENS.has(upperToken)) {
      return upperToken;
    }

    if (LOWERCASE_UNIT_TOKENS.has(lowerToken)) {
      return lowerToken;
    }

    if (/^[A-Z0-9]{2,4}$/.test(token) && token === upperToken) {
      return upperToken;
    }

    return lowerToken.charAt(0).toUpperCase() + lowerToken.slice(1);
  };

  return normalizedValue.replace(/[A-Za-z0-9]+/g, formatToken);
};

interface MedicationDisplayItem {
  name: string;
  medication?: Medication;
}

interface ResultsScreenProps {
  onScanAnother: () => void;
  scanResults: PrescriptionResponse;
}


const ResultsScreen = ({ onScanAnother, scanResults }: ResultsScreenProps) => {
  const [isRawTextOpen, setIsRawTextOpen] = useState(false);

  const filteredMedications = (scanResults.medications ?? []).filter((medication) => {
    const normalizedName = medication.name?.trim().toLowerCase() ?? "";
    const isPlaceholderMedication = normalizedName === "unable to parse medications";
    const hasMeaningfulName = normalizedName.length > 0 && !isPlaceholderMedication;
    return hasMeaningfulName;
  });

  const fallbackMedications = filteredMedications.length === 0 ? derivePossibleMedications(scanResults.raw_text) : [];
  const medicationsFromScan = filteredMedications.length > 0 ? filteredMedications : fallbackMedications;
  const isUsingFallbackMedications = filteredMedications.length === 0 && fallbackMedications.length > 0;

  const medicationMap = new Map<string, MedicationDisplayItem>();
  medicationsFromScan.forEach((medication) => {
    const key = normalizeMedicationKey(medication.name);
    if (!key || medicationMap.has(key)) {
      return;
    }
    medicationMap.set(key, { name: medication.name, medication });
  });

  const medicationsToDisplay = Array.from(medicationMap.values());

  return (
    <div className="space-y-4 pb-1">
      <div className="flex items-center gap-2 px-1">
        <Pill className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-semibold text-foreground">
          {medicationsToDisplay.length === 1
            ? "1 medication detected"
            : `${medicationsToDisplay.length} medications detected`}
        </h3>
      </div>

      {isUsingFallbackMedications && (
        <Card className="border-amber-500/30 bg-amber-500/5 p-3">
          <p className="text-sm text-amber-700">
            Structured parsing was unavailable, so names were derived from raw OCR text.
          </p>
        </Card>
      )}

      {medicationsToDisplay.length === 0 ? (
        <Card className="border bg-card/80 p-6 text-center">
          <AlertCircle className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
          <p className="text-sm font-medium text-foreground">No medications were detected in this scan.</p>
          <p className="mt-1 text-sm text-muted-foreground">Try another image or adjust image clarity and framing.</p>
        </Card>
      ) : (
        <div className="space-y-3">
          {medicationsToDisplay.map((item, index) => {
            const med = item.medication;
            const displayName = toDisplayMedicationName(item.name);
            const medicationKey = normalizeMedicationKey(item.name) || `medication-${index}`;
            const hasDetails = !!(med?.dosage || med?.quantity || med?.frequency || med?.signa);

            return (
              <motion.div
                key={`${medicationKey}-${index}`}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.18, delay: Math.min(index * 0.04, 0.2) }}
              >
                <Card className="border bg-card/90 px-4 py-4 shadow-sm md:px-5">
                  <h4 className="break-words text-base font-semibold leading-tight text-foreground">{displayName}</h4>
                  {hasDetails ? (
                    <div className="mt-3 space-y-2">
                      {med?.dosage && (
                        <div className="flex items-baseline gap-3">
                          <span className="w-20 shrink-0 text-xs font-medium text-muted-foreground">Dosage</span>
                          <span className="text-sm text-foreground">{med.dosage}</span>
                        </div>
                      )}
                      {med?.quantity && (
                        <div className="flex items-baseline gap-3">
                          <span className="w-20 shrink-0 text-xs font-medium text-muted-foreground">Quantity</span>
                          <span className="text-sm text-foreground">{med.quantity}</span>
                        </div>
                      )}
                      {med?.frequency && (
                        <div className="flex items-baseline gap-3">
                          <span className="w-20 shrink-0 text-xs font-medium text-muted-foreground">Frequency</span>
                          <span className="text-sm text-foreground">{med.frequency}</span>
                        </div>
                      )}
                      {med?.signa && (
                        <div className="flex items-baseline gap-3">
                          <span className="w-20 shrink-0 text-xs font-medium text-muted-foreground">Signa</span>
                          <span className="text-sm text-foreground">{med.signa}</span>
                        </div>
                      )}
                    </div>
                  ) : (
                    <p className="mt-2 text-sm text-muted-foreground">No details extracted.</p>
                  )}
                  {med?.match_method && (
                    <p className="mt-3 text-xs text-muted-foreground/60">Matched via {med.match_method}</p>
                  )}
                </Card>
              </motion.div>
            );
          })}
        </div>
      )}

      {scanResults.raw_text && (
        <Card className="border bg-card/65 p-0">
          <Collapsible open={isRawTextOpen} onOpenChange={setIsRawTextOpen}>
            <CollapsibleTrigger className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-muted/20">
              <div className="flex items-center gap-2">
                <FileText className="h-4 w-4 text-primary" />
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Source OCR</p>
                  <p className="text-sm font-semibold text-foreground">Raw extracted text</p>
                </div>
              </div>
              <Button variant="ghost" size="sm">
                {isRawTextOpen ? "Hide" : "Show"}
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="px-4 pb-4">
              <pre className="max-h-56 overflow-auto rounded-md border bg-muted/30 p-3 text-xs font-mono whitespace-pre-wrap">
                {scanResults.raw_text}
              </pre>
            </CollapsibleContent>
          </Collapsible>
        </Card>
      )}

      <Button size="lg" onClick={onScanAnother} variant="outline" className="w-full bg-card/70">
        <Scan className="mr-2 h-4 w-4" />
        Scan Another Prescription
      </Button>
    </div>
  );
};

export default ResultsScreen;
