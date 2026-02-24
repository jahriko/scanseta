import { useState } from "react";
import { motion } from "framer-motion";
import {
  Scan,
  Pill,
  FileText,
  AlertCircle,
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

const normalizeStatus = (value?: string | null): string => (value ?? "").trim().toLowerCase();

const getEnrichmentBanner = (status: string): { title: string; detail: string; className: string } => {
  switch (status) {
    case "queued":
      return {
        title: "Validation queued",
        detail: "Drug validation is queued and will begin shortly.",
        className: "border-blue-500/30 bg-blue-500/5 text-blue-700",
      };
    case "running":
      return {
        title: "Validation in progress",
        detail: "FDA and PNDF checks are still running in the background.",
        className: "border-blue-500/30 bg-blue-500/5 text-blue-700",
      };
    case "completed":
      return {
        title: "Validation complete",
        detail: "FDA and PNDF checks finished.",
        className: "border-green-500/30 bg-green-500/5 text-green-700",
      };
    case "partial":
      return {
        title: "Validation partially complete",
        detail: "One data source completed and one source timed out or failed.",
        className: "border-amber-500/30 bg-amber-500/5 text-amber-700",
      };
    case "timed_out":
      return {
        title: "Validation timed out",
        detail: "Live validation timed out. Try re-running validation for this prescription.",
        className: "border-amber-500/30 bg-amber-500/5 text-amber-700",
      };
    case "failed":
      return {
        title: "Validation failed",
        detail: "Live validation failed due to source or network errors.",
        className: "border-destructive/40 bg-destructive/5 text-destructive",
      };
    default:
      return {
        title: "Validation not requested",
        detail: "Only OCR extraction is available for this result.",
        className: "border-muted bg-muted/20 text-muted-foreground",
      };
  }
};

const getSourceStateLabel = (
  sourceStatus: string,
  hasItem: boolean,
  found: boolean,
  errorCode: string | null | undefined,
  sourceName: "FDA" | "PNDF",
): string => {
  if (hasItem) {
    if (errorCode === "timeout") {
      return "Timed out";
    }
    if (errorCode === "scrape_error") {
      return "Failed";
    }
    if (found) {
      return sourceName === "FDA" ? "Verified" : "Found";
    }
    return sourceName === "FDA" ? "No match" : "No profile";
  }

  switch (sourceStatus) {
    case "queued":
      return "Queued";
    case "running":
      return "Validating";
    case "timed_out":
      return "Timed out";
    case "failed":
      return "Failed";
    case "completed":
      return sourceName === "FDA" ? "No match" : "No profile";
    default:
      return "Pending";
  }
};

const getSourceStateClass = (statusLabel: string): string => {
  if (statusLabel === "Verified" || statusLabel === "Found") {
    return "text-[11px] font-medium bg-green-500/10 text-green-700";
  }
  if (statusLabel === "Timed out" || statusLabel === "Failed") {
    return "text-[11px] font-medium bg-destructive/10 text-destructive";
  }
  if (statusLabel === "Validating" || statusLabel === "Queued" || statusLabel === "Pending") {
    return "text-[11px] font-medium bg-blue-500/10 text-blue-700";
  }
  return "text-[11px] font-medium bg-amber-500/10 text-amber-700";
};

const getSourceMissingMessage = (sourceStatus: string, sourceName: "FDA" | "PNDF"): string => {
  if (sourceStatus === "queued" || sourceStatus === "running") {
    return `${sourceName} validation is in progress.`;
  }
  if (sourceStatus === "timed_out") {
    return `${sourceName} validation timed out before a result was returned.`;
  }
  if (sourceStatus === "failed") {
    return `${sourceName} validation failed due to a source error.`;
  }
  if (sourceStatus === "completed") {
    return sourceName === "FDA"
      ? "No FDA match was returned for this medication."
      : "No PNDF profile was returned for this medication.";
  }
  return `${sourceName} validation has not returned data yet.`;
};

interface MedicationDisplayItem {
  name: string;
  medication?: Medication;
  fda?: FDAVerificationItem;
  pndf?: PNDFEnrichmentItem;
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
  const enrichmentStatus = normalizeStatus(scanResults.enrichment_status || (scanResults.can_enrich ? "running" : "not_requested"));
  const fdaEnrichmentStatus = normalizeStatus(scanResults.fda_enrichment_status || (fdaItems.length > 0 ? "completed" : scanResults.can_enrich ? "running" : "pending"));
  const pndfEnrichmentStatus = normalizeStatus(scanResults.pndf_enrichment_status || (pndfItems.length > 0 ? "completed" : scanResults.can_enrich ? "running" : "pending"));
  const enrichmentBanner = getEnrichmentBanner(enrichmentStatus);

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
    });
  });

  const medicationsToDisplay = Array.from(medicationMap.values());
  return (
    <div className="space-y-4">
      {/* <div className="space-y-2">
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
      </div> */}

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Pill className="h-5 w-5 text-primary" />
          <h3 className="text-lg font-semibold">Medications</h3>
        </div>
        <Badge variant="secondary">{medicationsToDisplay.length}</Badge>
      </div>

      {scanResults.can_enrich && (
        <Card className={`p-3 ${enrichmentBanner.className}`}>
          <p className="text-sm font-semibold">{enrichmentBanner.title}</p>
          <p className="text-sm">
            {enrichmentBanner.detail} FDA: {fdaEnrichmentStatus || "pending"} | PNDF: {pndfEnrichmentStatus || "pending"}
          </p>
        </Card>
      )}

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
            const displayName = toDisplayMedicationName(item.name);
            const extractionSummary = med?.dosage
              ? `Dosage ${med.dosage}`
              : med?.signa
                ? `Signa ${med.signa}`
                : "No structured extraction details";
            const fdaStatus = getSourceStateLabel(
              fdaEnrichmentStatus,
              !!item.fda,
              !!item.fda?.found,
              item.fda?.error_code,
              "FDA",
            );
            const pndfStatus = getSourceStateLabel(
              pndfEnrichmentStatus,
              !!item.pndf,
              !!item.pndf?.found,
              item.pndf?.error_code,
              "PNDF",
            );
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
                <Card className="border p-0 shadow-sm">
                  <Collapsible>
                    <CollapsibleTrigger className="flex w-full items-center justify-between gap-3 px-4 py-4 text-left transition-colors hover:bg-muted/30 md:px-5">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <h4 className="text-base font-semibold leading-tight">{displayName}</h4>
                        </div>
                        <p className="mt-2 line-clamp-2 rounded-md bg-muted/30 px-2 py-1.5 text-sm text-foreground/90">
                          {extractionSummary}
                        </p>
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          <Badge
                            variant="secondary"
                            className={getSourceStateClass(fdaStatus)}
                          >
                            FDA {fdaStatus}
                          </Badge>
                          <Badge
                            variant="secondary"
                            className={getSourceStateClass(pndfStatus)}
                          >
                            PNDF {pndfStatus}
                          </Badge>
                        </div>
                      </div>
                      <div className="rounded-md border bg-muted/20 p-1.5">
                        <ChevronDown className="h-4 w-4 text-muted-foreground" />
                      </div>
                    </CollapsibleTrigger>
                    <CollapsibleContent className="px-4 pb-4 md:px-5">
                      <div className="grid gap-3 lg:grid-cols-3">
                        <div className="rounded-md border bg-muted/20 p-3.5 space-y-2.5">
                          <div className="flex items-center gap-2 text-base font-semibold">
                            <BookOpenText className="h-4 w-4 text-primary" />
                            Extraction
                          </div>
                          {med?.dosage && <p className="text-sm"><span className="font-semibold">Dosage:</span> {med.dosage}</p>}
                          {med?.signa && <p className="text-sm"><span className="font-semibold">Signa:</span> {med.signa}</p>}
                          {med?.frequency && <p className="text-sm"><span className="font-semibold">Frequency:</span> {med.frequency}</p>}
                          {med?.match_method && <p className="text-sm text-muted-foreground"><span className="font-semibold">Match:</span> {med.match_method}</p>}
                          {!med?.dosage && !med?.signa && !med?.frequency && !med?.match_method && (
                            <p className="text-sm text-muted-foreground">No extra OCR structure available.</p>
                          )}
                        </div>

                        <div className="rounded-md border bg-muted/20 p-3.5 space-y-2.5">
                          <div className="flex items-center gap-2 text-base font-semibold">
                            {item.fda?.found ? (
                              <ShieldCheck className="h-4 w-4 text-green-600" />
                            ) : (
                              <ShieldAlert className="h-4 w-4 text-amber-600" />
                            )}
                            FDA
                          </div>
                          {item.fda ? (
                            <>
                              <Badge variant="secondary" className={getSourceStateClass(fdaStatus)}>
                                {fdaStatus}
                              </Badge>
                              {fdaBestMatch?.generic_name && <p className="text-sm"><span className="font-semibold">Generic:</span> {fdaBestMatch.generic_name}</p>}
                              {fdaBestMatch?.brand_name && <p className="text-sm"><span className="font-semibold">Brand:</span> {fdaBestMatch.brand_name}</p>}
                              {fdaBestMatch?.classification && <p className="text-sm"><span className="font-semibold">Class:</span> {fdaBestMatch.classification}</p>}
                              {fdaBestMatch?.registration_number && <p className="text-sm"><span className="font-semibold">Reg.:</span> {fdaBestMatch.registration_number}</p>}
                              {item.fda.error && <p className="text-sm text-destructive">{item.fda.error}</p>}
                            </>
                          ) : (
                            <p className="text-sm text-muted-foreground">{getSourceMissingMessage(fdaEnrichmentStatus, "FDA")}</p>
                          )}
                        </div>

                        <div className="rounded-md border bg-muted/20 p-3.5 space-y-2.5">
                          <div className="flex items-center gap-2 text-base font-semibold">
                            <Pill className="h-4 w-4 text-accent" />
                            PNDF
                          </div>
                          {item.pndf ? (
                            <>
                              <Badge variant="secondary" className={getSourceStateClass(pndfStatus)}>
                                {pndfStatus}
                              </Badge>
                              {item.pndf.atc_code && <p className="text-sm"><span className="font-semibold">ATC:</span> {item.pndf.atc_code}</p>}
                              {classificationValues.length > 0 && (
                                <p className="text-sm"><span className="font-semibold">Class:</span> {classificationValues.join(", ")}</p>
                              )}
                              {dosageForms.length > 0 && <p className="text-sm"><span className="font-semibold">Forms:</span> {dosageForms.slice(0, 2).join("; ")}</p>}
                              {item.pndf.message && <p className="text-sm text-muted-foreground">{item.pndf.message}</p>}
                              {item.pndf.error && <p className="text-sm text-destructive">{item.pndf.error}</p>}
                            </>
                          ) : (
                            <p className="text-sm text-muted-foreground">{getSourceMissingMessage(pndfEnrichmentStatus, "PNDF")}</p>
                          )}
                        </div>
                      </div>

                      {clinicalNotes.length > 0 && (
                        <div className="mt-3 rounded-md border bg-muted/10 p-3.5">
                          <p className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Clinical notes</p>
                          <div className="grid gap-2">
                            {clinicalNotes.slice(0, 4).map((note) => (
                              <div key={`${item.name}-${note.label}`}>
                                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{note.label}</p>
                                <p className="text-sm whitespace-pre-wrap leading-relaxed">{note.value}</p>
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
