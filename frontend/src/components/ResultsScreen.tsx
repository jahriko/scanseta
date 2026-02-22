import { useState } from "react";
import { motion } from "framer-motion";
import {
  Scan,
  Pill,
  FileText,
  AlertCircle,
  Clock,
  ShieldCheck,
  ShieldAlert,
  BookOpenText,
  ChevronDown,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  PrescriptionResponse,
  Medication,
  FDAVerificationItem,
  PNDFEnrichmentItem,
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

interface MedicationDisplayItem {
  name: string;
  medication?: Medication;
  fda?: FDAVerificationItem;
  pndf?: PNDFEnrichmentItem;
  source: "parsed" | "fallback" | "enriched";
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
  const pndfItems = scanResults.pndf_enriched ?? scanResults.enriched_medications ?? scanResults.enriched ?? [];
  const fdaItems = scanResults.fda_verification ?? [];

  const fdaByKey = new Map<string, FDAVerificationItem>();
  fdaItems.forEach((item) => {
    const key = normalizeMedicationKey(item.query);
    if (key.length > 0) {
      fdaByKey.set(key, item);
    }
  });

  const pndfByKey = new Map<string, PNDFEnrichmentItem>();
  pndfItems.forEach((item) => {
    const key = normalizeMedicationKey(item.name);
    if (key.length > 0) {
      pndfByKey.set(key, item);
    }
  });

  const medicationMap = new Map<string, MedicationDisplayItem>();
  medicationsFromScan.forEach((medication) => {
    const key = normalizeMedicationKey(medication.name);
    if (!key || medicationMap.has(key)) {
      return;
    }

    medicationMap.set(key, {
      name: medication.name,
      medication,
      fda: fdaByKey.get(key),
      pndf: pndfByKey.get(key),
      source: filteredMedications.length > 0 ? "parsed" : "fallback",
    });
  });

  fdaByKey.forEach((fda, key) => {
    const existing = medicationMap.get(key);
    if (existing) {
      existing.fda = existing.fda ?? fda;
      return;
    }
    medicationMap.set(key, {
      name: fda.query,
      fda,
      pndf: pndfByKey.get(key),
      source: "enriched",
    });
  });

  pndfByKey.forEach((pndf, key) => {
    const existing = medicationMap.get(key);
    if (existing) {
      existing.pndf = existing.pndf ?? pndf;
      return;
    }
    medicationMap.set(key, {
      name: pndf.name,
      fda: fdaByKey.get(key),
      pndf,
      source: "enriched",
    });
  });

  const medicationsToDisplay = Array.from(medicationMap.values());
  const fdaVerifiedCount = medicationsToDisplay.filter((item) => item.fda?.found).length;
  const pndfFoundCount = medicationsToDisplay.filter((item) => item.pndf?.found).length;
  const processingTime =
    Number.isFinite(scanResults.processing_time) && scanResults.processing_time >= 0
      ? scanResults.processing_time
      : 0;

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <div className="inline-flex items-center gap-2 rounded-md bg-accent/10 px-3 py-1 text-sm text-accent">
          <ShieldCheck className="h-4 w-4" />
          Analysis complete
        </div>
        <h2 className="text-2xl font-semibold">Prescription summary</h2>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        <div className="rounded-md border bg-muted/30 p-3">
          <div className="text-xs uppercase text-muted-foreground">Processing time</div>
          <div className="mt-1 flex items-center gap-2 text-sm font-medium">
            <Clock className="h-4 w-4 text-primary" />
            {processingTime.toFixed(2)}s
          </div>
        </div>
        <div className="rounded-md border bg-muted/30 p-3">
          <div className="text-xs uppercase text-muted-foreground">Medication entries</div>
          <div className="mt-1 text-sm font-medium">{medicationsToDisplay.length}</div>
        </div>
        <div className="rounded-md border bg-muted/30 p-3">
          <div className="text-xs uppercase text-muted-foreground">FDA verified</div>
          <div className="mt-1 text-sm font-medium">{fdaVerifiedCount}</div>
        </div>
        <div className="rounded-md border bg-muted/30 p-3">
          <div className="text-xs uppercase text-muted-foreground">PNDF enriched</div>
          <div className="mt-1 text-sm font-medium">{pndfFoundCount}</div>
        </div>
      </div>

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Pill className="h-5 w-5 text-primary" />
          <h3 className="text-lg font-semibold">Medications</h3>
        </div>
        <Badge variant="secondary">{medicationsToDisplay.length}</Badge>
      </div>

      {isUsingFallbackMedications && (
        <Card className="border-amber-500/30 bg-amber-500/5 p-3">
          <p className="text-sm text-amber-700">
            Structured parsing was unavailable, so names were derived from raw OCR text.
          </p>
        </Card>
      )}

      {medicationsToDisplay.length === 0 ? (
        <Card className="p-6 text-center border">
          <AlertCircle className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">No medications were detected in this scan.</p>
        </Card>
      ) : (
        <div className="space-y-2">
          {medicationsToDisplay.map((item, index) => {
            const med = item.medication;
            const confidence =
              typeof med?.confidence === "number" && Number.isFinite(med.confidence)
                ? `${Math.round(Math.max(0, Math.min(1, med.confidence)) * 100)}%`
                : null;
            const fdaBestMatch = item.fda?.best_match;
            const classificationValues = item.pndf?.classification
              ? Object.values(item.pndf.classification)
                  .filter((value): value is string => typeof value === "string" && value.trim().length > 0)
              : [];
            const dosageForms = (item.pndf?.dosage_forms ?? [])
              .map((form) =>
                Object.values(form)
                  .map((value) => String(value))
                  .filter((value) => value.trim().length > 0)
                  .join(" / ")
              )
              .filter((value) => value.length > 0);

            const clinicalNotes = [
              { label: "Indications", value: item.pndf?.indications },
              { label: "Contraindications", value: item.pndf?.contraindications },
              { label: "Precautions", value: item.pndf?.precautions },
              { label: "Adverse Reactions", value: item.pndf?.adverse_reactions },
              { label: "Drug Interactions", value: item.pndf?.drug_interactions },
              { label: "Mechanism", value: item.pndf?.mechanism_of_action },
              { label: "Dosage Instructions", value: item.pndf?.dosage_instructions },
              { label: "Administration", value: item.pndf?.administration },
            ].filter((note) => !!note.value && note.value.trim().length > 0);

            return (
              <motion.div
                key={`${normalizeMedicationKey(item.name)}-${index}`}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.18, delay: Math.min(index * 0.04, 0.2) }}
              >
                <Card className="border p-0">
                  <Collapsible>
                    <CollapsibleTrigger className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-muted/30">
                      <div>
                        <div className="text-sm font-semibold">{item.name}</div>
                        <div className="mt-1 flex flex-wrap items-center gap-2">
                          <Badge variant="secondary" className="text-xs">
                            {item.source === "parsed"
                              ? "OCR parse"
                              : item.source === "fallback"
                                ? "Raw text"
                                : "Enriched"}
                          </Badge>
                          {confidence && <Badge className="text-xs bg-primary/10 text-primary">Confidence {confidence}</Badge>}
                        </div>
                      </div>
                      <ChevronDown className="h-4 w-4 text-muted-foreground" />
                    </CollapsibleTrigger>
                    <CollapsibleContent className="px-4 pb-4">
                      <div className="grid gap-3 lg:grid-cols-3">
                        <div className="rounded-md border bg-muted/20 p-3 space-y-2">
                          <div className="flex items-center gap-2 text-sm font-semibold">
                            <BookOpenText className="h-4 w-4 text-primary" />
                            Extraction
                          </div>
                          {med?.dosage && <p className="text-xs"><span className="font-semibold">Dosage:</span> {med.dosage}</p>}
                          {med?.signa && <p className="text-xs"><span className="font-semibold">Signa:</span> {med.signa}</p>}
                          {med?.frequency && <p className="text-xs"><span className="font-semibold">Frequency:</span> {med.frequency}</p>}
                          {med?.match_method && <p className="text-xs text-muted-foreground"><span className="font-semibold">Match:</span> {med.match_method}</p>}
                          {!med?.dosage && !med?.signa && !med?.frequency && !med?.match_method && (
                            <p className="text-xs text-muted-foreground">No extra OCR structure available.</p>
                          )}
                        </div>

                        <div className="rounded-md border bg-muted/20 p-3 space-y-2">
                          <div className="flex items-center gap-2 text-sm font-semibold">
                            {item.fda?.found ? (
                              <ShieldCheck className="h-4 w-4 text-green-600" />
                            ) : (
                              <ShieldAlert className="h-4 w-4 text-amber-600" />
                            )}
                            FDA
                          </div>
                          {item.fda ? (
                            <>
                              <Badge variant="secondary" className={item.fda.found ? "text-xs bg-green-500/10 text-green-700" : "text-xs bg-amber-500/10 text-amber-700"}>
                                {item.fda.found ? "Verified" : "No match"}
                              </Badge>
                              {fdaBestMatch?.generic_name && <p className="text-xs"><span className="font-semibold">Generic:</span> {fdaBestMatch.generic_name}</p>}
                              {fdaBestMatch?.brand_name && <p className="text-xs"><span className="font-semibold">Brand:</span> {fdaBestMatch.brand_name}</p>}
                              {fdaBestMatch?.classification && <p className="text-xs"><span className="font-semibold">Class:</span> {fdaBestMatch.classification}</p>}
                              {fdaBestMatch?.registration_number && <p className="text-xs"><span className="font-semibold">Reg.:</span> {fdaBestMatch.registration_number}</p>}
                              {item.fda.error && <p className="text-xs text-destructive">{item.fda.error}</p>}
                            </>
                          ) : (
                            <p className="text-xs text-muted-foreground">FDA data not returned.</p>
                          )}
                        </div>

                        <div className="rounded-md border bg-muted/20 p-3 space-y-2">
                          <div className="flex items-center gap-2 text-sm font-semibold">
                            <Pill className="h-4 w-4 text-accent" />
                            PNDF
                          </div>
                          {item.pndf ? (
                            <>
                              <Badge variant="secondary" className={item.pndf.found ? "text-xs bg-green-500/10 text-green-700" : "text-xs bg-amber-500/10 text-amber-700"}>
                                {item.pndf.found ? "Found" : "No profile"}
                              </Badge>
                              {item.pndf.atc_code && <p className="text-xs"><span className="font-semibold">ATC:</span> {item.pndf.atc_code}</p>}
                              {classificationValues.length > 0 && (
                                <p className="text-xs"><span className="font-semibold">Class:</span> {classificationValues.join(", ")}</p>
                              )}
                              {dosageForms.length > 0 && <p className="text-xs"><span className="font-semibold">Forms:</span> {dosageForms.slice(0, 2).join("; ")}</p>}
                              {item.pndf.message && <p className="text-xs text-muted-foreground">{item.pndf.message}</p>}
                              {item.pndf.error && <p className="text-xs text-destructive">{item.pndf.error}</p>}
                            </>
                          ) : (
                            <p className="text-xs text-muted-foreground">PNDF data not returned.</p>
                          )}
                        </div>
                      </div>

                      {clinicalNotes.length > 0 && (
                        <div className="mt-3 rounded-md border bg-muted/10 p-3">
                          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Clinical notes</p>
                          <div className="grid gap-2">
                            {clinicalNotes.slice(0, 4).map((note) => (
                              <div key={`${item.name}-${note.label}`}>
                                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{note.label}</p>
                                <p className="text-xs whitespace-pre-wrap">{note.value}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </CollapsibleContent>
                  </Collapsible>
                </Card>
              </motion.div>
            );
          })}
        </div>
      )}

      {scanResults.raw_text && (
        <Card className="border p-0">
          <Collapsible open={isRawTextOpen} onOpenChange={setIsRawTextOpen}>
            <CollapsibleTrigger className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-muted/30">
              <div className="flex items-center gap-2">
                <FileText className="h-4 w-4 text-primary" />
                <span className="text-sm font-semibold">Raw extracted text</span>
              </div>
              <Button variant="ghost" size="sm">
                {isRawTextOpen ? "Hide" : "Show"}
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="px-4 pb-4">
              <pre className="max-h-56 overflow-auto rounded-md border bg-muted/30 p-3 text-xs whitespace-pre-wrap font-mono">
                {scanResults.raw_text}
              </pre>
            </CollapsibleContent>
          </Collapsible>
        </Card>
      )}

      <Button size="lg" onClick={onScanAnother} className="w-full">
        <Scan className="mr-2 h-4 w-4" />
        Scan Another Prescription
      </Button>
    </div>
  );
};

export default ResultsScreen;