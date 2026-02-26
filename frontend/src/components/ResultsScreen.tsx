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
import { buildPatientMedicationSummary } from "@/lib/patient-medication-summary";

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
  if (statusLabel === "Verified" || statusLabel === "Found" || statusLabel === "Complete") {
    return "border-green-500/30 bg-green-500/10 text-green-700";
  }
  if (statusLabel === "Timed out" || statusLabel === "Failed") {
    return "border-destructive/30 bg-destructive/10 text-destructive";
  }
  if (statusLabel === "Validating" || statusLabel === "Queued" || statusLabel === "Pending" || statusLabel === "Running") {
    return "border-blue-500/30 bg-blue-500/10 text-blue-700";
  }
  if (statusLabel === "Not requested") {
    return "border-muted bg-muted/40 text-muted-foreground";
  }
  return "border-amber-500/30 bg-amber-500/10 text-amber-700";
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

const toStatusPillText = (status: string): string => {
  switch (status) {
    case "queued":
      return "Queued";
    case "running":
      return "Running";
    case "completed":
      return "Complete";
    case "partial":
      return "Partial";
    case "timed_out":
      return "Timed out";
    case "failed":
      return "Failed";
    case "not_requested":
      return "Not requested";
    default:
      return "Pending";
  }
};

const formatDosageFormsPreview = (forms?: Array<Record<string, unknown>>): string[] => {
  if (!forms || forms.length === 0) {
    return [];
  }

  return forms
    .map((form) => {
      const route = String(form.route ?? "").trim().toUpperCase();
      const doseForm = String(form.form ?? "").trim();
      const status = String(form.status ?? "").trim();
      const combined = [route, doseForm, status].filter((value) => value.length > 0).join(" - ");
      return combined.replace(/\s+/g, " ").trim();
    })
    .filter((value) => value.length > 0)
    .filter((value) => value.length <= 110)
    .filter((value) => !/classification|search|total visitors|department of health/i.test(value))
    .slice(0, 2);
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

interface DetailRowProps {
  label: string;
  value: string;
  subtle?: boolean;
}

const DetailRow = ({ label, value, subtle = false }: DetailRowProps) => (
  <p className={`text-sm leading-relaxed ${subtle ? "text-muted-foreground" : "text-foreground"}`}>
    <span className="font-semibold text-foreground">{label}:</span> {value}
  </p>
);

const ResultsScreen = ({ onScanAnother, scanResults }: ResultsScreenProps) => {
  const [isRawTextOpen, setIsRawTextOpen] = useState(false);
  const [openMedicationKey, setOpenMedicationKey] = useState<string | null>(null);

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
    <div className="space-y-4 pb-1">
      <div className="rounded-xl border bg-card/85 p-4 shadow-sm">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Medication Results</p>
            <div className="flex items-center gap-2">
              <Pill className="h-5 w-5 text-primary" />
              <h3 className="text-lg font-semibold leading-tight text-foreground">Detected medications</h3>
            </div>
          </div>
          <Badge variant="outline" className="bg-muted/40 text-foreground">
            {medicationsToDisplay.length} total
          </Badge>
        </div>

        {scanResults.can_enrich ? (
          <div className={`mt-3 rounded-lg border p-3 ${enrichmentBanner.className}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-semibold">{enrichmentBanner.title}</p>
              <Badge variant="outline" className={`${getSourceStateClass(toStatusPillText(enrichmentStatus))} text-[11px]`}>
                {toStatusPillText(enrichmentStatus)}
              </Badge>
            </div>
            <p className="mt-1.5 text-sm">{enrichmentBanner.detail}</p>
            <div className="mt-2.5 flex flex-wrap items-center gap-2">
              <Badge variant="outline" className={`${getSourceStateClass(toStatusPillText(fdaEnrichmentStatus))} text-[11px]`}>
                FDA {toStatusPillText(fdaEnrichmentStatus)}
              </Badge>
              <Badge variant="outline" className={`${getSourceStateClass(toStatusPillText(pndfEnrichmentStatus))} text-[11px]`}>
                PNDF {toStatusPillText(pndfEnrichmentStatus)}
              </Badge>
            </div>
          </div>
        ) : (
          <div className="mt-3 rounded-lg border border-muted bg-muted/20 p-3 text-sm text-muted-foreground">
            Validation was not requested for this scan. OCR extraction details are still available below.
          </div>
        )}
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
            const medicationKey = normalizeMedicationKey(item.name) || `medication-${index}`;
            const isOpen = openMedicationKey === medicationKey;
            const dosageFormPreview = formatDosageFormsPreview(item.pndf?.dosage_forms);
            const patientSummary = buildPatientMedicationSummary(displayName, item.pndf);

            return (
              <motion.div
                key={`${medicationKey}-${index}`}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.18, delay: Math.min(index * 0.04, 0.2) }}
              >
                <Card className="overflow-hidden border bg-card/90 shadow-sm">
                  <Collapsible open={isOpen} onOpenChange={(nextOpen) => setOpenMedicationKey(nextOpen ? medicationKey : null)}>
                    <CollapsibleTrigger className="flex w-full items-center justify-between gap-3 px-4 py-4 text-left transition-colors hover:bg-muted/30 md:px-5">
                      <div className="min-w-0 space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <h4 className="text-base font-semibold leading-tight text-foreground">{displayName}</h4>
                          <span className="inline-flex max-w-full items-center rounded-full border bg-muted/30 px-2.5 py-1 text-xs text-foreground/85">
                            <span className="truncate">{extractionSummary}</span>
                          </span>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="outline" className={`${getSourceStateClass(fdaStatus)} text-[11px]`}>
                            FDA {fdaStatus}
                          </Badge>
                          <Badge variant="outline" className={`${getSourceStateClass(pndfStatus)} text-[11px]`}>
                            PNDF {pndfStatus}
                          </Badge>
                        </div>
                      </div>

                      <div className="grid h-8 w-8 shrink-0 place-items-center rounded-md border bg-card/70">
                        <ChevronDown className={`h-4 w-4 transition-transform ${isOpen ? "rotate-180 text-foreground" : "text-muted-foreground"}`} />
                      </div>
                    </CollapsibleTrigger>

                    <CollapsibleContent className="px-4 pb-4 md:px-5">
                      <div className="grid gap-3 lg:grid-cols-3">
                        <div className="space-y-2.5 rounded-lg border bg-muted/20 p-3.5">
                          <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.06em] text-muted-foreground">
                            <BookOpenText className="h-4 w-4 text-primary" />
                            Extraction
                          </div>
                          {med?.dosage && <DetailRow label="Dosage" value={med.dosage} />}
                          {med?.signa && <DetailRow label="Signa" value={med.signa} />}
                          {med?.frequency && <DetailRow label="Frequency" value={med.frequency} />}
                          {med?.match_method && <DetailRow label="Match" value={med.match_method} subtle />}
                          {!med?.dosage && !med?.signa && !med?.frequency && !med?.match_method && (
                            <p className="rounded-md border border-dashed border-border bg-card/60 px-2.5 py-2 text-sm text-muted-foreground">
                              No extra OCR structure available.
                            </p>
                          )}
                        </div>

                        <div className="space-y-2.5 rounded-lg border bg-muted/20 p-3.5">
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.06em] text-muted-foreground">
                              {item.fda?.found ? (
                                <ShieldCheck className="h-4 w-4 text-green-600" />
                              ) : (
                                <ShieldAlert className="h-4 w-4 text-amber-600" />
                              )}
                              FDA
                            </div>
                            <Badge variant="outline" className={`${getSourceStateClass(fdaStatus)} text-[11px]`}>
                              {fdaStatus}
                            </Badge>
                          </div>
                          {item.fda ? (
                            <>
                              {fdaBestMatch?.generic_name && <DetailRow label="Generic" value={fdaBestMatch.generic_name} />}
                              {fdaBestMatch?.brand_name && <DetailRow label="Brand" value={fdaBestMatch.brand_name} />}
                              {fdaBestMatch?.classification && <DetailRow label="Class" value={fdaBestMatch.classification} />}
                              {fdaBestMatch?.registration_number && <DetailRow label="Reg." value={fdaBestMatch.registration_number} />}
                              {item.fda.error && <p className="text-sm text-destructive">{item.fda.error}</p>}
                              {!fdaBestMatch?.generic_name && !fdaBestMatch?.brand_name && !fdaBestMatch?.classification && !fdaBestMatch?.registration_number && (
                                <p className="rounded-md border border-dashed border-border bg-card/60 px-2.5 py-2 text-sm text-muted-foreground">
                                  {getSourceMissingMessage(fdaEnrichmentStatus, "FDA")}
                                </p>
                              )}
                            </>
                          ) : (
                            <p className="rounded-md border border-dashed border-border bg-card/60 px-2.5 py-2 text-sm text-muted-foreground">
                              {getSourceMissingMessage(fdaEnrichmentStatus, "FDA")}
                            </p>
                          )}
                        </div>

                        <div className="space-y-2.5 rounded-lg border bg-muted/20 p-3.5">
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.06em] text-muted-foreground">
                              <Pill className="h-4 w-4 text-accent" />
                              PNDF
                            </div>
                            <Badge variant="outline" className={`${getSourceStateClass(pndfStatus)} text-[11px]`}>
                              {pndfStatus}
                            </Badge>
                          </div>
                          {item.pndf ? (
                            <>
                              {item.pndf.atc_code && <DetailRow label="ATC" value={item.pndf.atc_code} />}
                              {dosageFormPreview.length > 0 && <DetailRow label="Forms" value={dosageFormPreview.join("; ")} />}
                              {item.pndf.message && <p className="text-sm text-muted-foreground">{item.pndf.message}</p>}
                              {item.pndf.error && <p className="text-sm text-destructive">{item.pndf.error}</p>}
                              {!item.pndf.atc_code && dosageFormPreview.length === 0 && !item.pndf.message && !item.pndf.error && (
                                <p className="rounded-md border border-dashed border-border bg-card/60 px-2.5 py-2 text-sm text-muted-foreground">
                                  {getSourceMissingMessage(pndfEnrichmentStatus, "PNDF")}
                                </p>
                              )}
                            </>
                          ) : (
                            <p className="rounded-md border border-dashed border-border bg-card/60 px-2.5 py-2 text-sm text-muted-foreground">
                              {getSourceMissingMessage(pndfEnrichmentStatus, "PNDF")}
                            </p>
                          )}
                        </div>
                      </div>

                      {patientSummary.sections.length > 0 && (
                        <div className="mt-3 rounded-lg border bg-card/70 p-3.5">
                          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">Patient Summary</p>
                          <div className="grid gap-2 md:grid-cols-2">
                            {patientSummary.sections.map((summarySection) => (
                              <div key={`${item.name}-${summarySection.title}`} className="rounded-md bg-muted/25 px-2.5 py-2">
                                <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{summarySection.title}</p>
                                <ul className="mt-1 space-y-1">
                                  {summarySection.bullets.map((bullet) => (
                                    <li key={`${summarySection.title}-${bullet}`} className="text-sm leading-relaxed">
                                      - {bullet}
                                    </li>
                                  ))}
                                </ul>
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
