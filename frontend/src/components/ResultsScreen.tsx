import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Scan, FileText, AlertCircle, AlertTriangle, ChevronDown, User, CheckCircle2, XCircle, Clock, Pill, Copy, Check, Package, Repeat } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  PrescriptionResponse,
  Medication,
  FDAVerificationItem,
  PNDFEnrichmentItem,
} from "@/lib/prescription-api";

// ─── helpers ────────────────────────────────────────────────────────────────

const derivePossibleMedications = (rawText?: string): Medication[] => {
  if (!rawText) return [];
  const tokens = rawText
    .split(/[\n,;+]+/)
    .map((t) => t.trim())
    .filter((t) => t.length > 0 && /[a-zA-Z]/.test(t));
  return Array.from(new Set(tokens)).map((name) => ({ name, confidence: 0.5 }));
};

const normalizeMedicationKey = (value?: string | null) =>
  (value ?? "").trim().toLowerCase().replace(/\s+/g, " ");

const UPPERCASE_TOKENS = new Set(["IV","IM","XR","SR","ER","IR","CR","EC","OD","BD","TID","QID","PRN","PO"]);
const LOWERCASE_UNITS = new Set(["mg","mcg","g","ml","kg"]);

const toDisplayName = (value?: string | null): string => {
  const v = (value ?? "").trim().replace(/\s+/g, " ");
  if (!v) return "";
  return v.replace(/[A-Za-z0-9]+/g, (token) => {
    if (/^\d+$/.test(token)) return token;
    if (UPPERCASE_TOKENS.has(token.toUpperCase())) return token.toUpperCase();
    if (LOWERCASE_UNITS.has(token.toLowerCase())) return token.toLowerCase();
    if (/^[A-Z0-9]{2,4}$/.test(token)) return token.toUpperCase();
    return token.charAt(0).toUpperCase() + token.slice(1).toLowerCase();
  });
};

// ─── verification status helpers ────────────────────────────────────────────

type VerificationState = "verified" | "not_found" | "pending" | "none";

interface DrugVerification {
  fda: VerificationState;
  pndf: VerificationState;
}

const getVerification = (
  name: string,
  enrichmentStatus: string,
  fdaItems?: FDAVerificationItem[] | null,
  pndfItems?: PNDFEnrichmentItem[] | null,
): DrugVerification => {
  const isTerminal = ["completed", "partial"].includes(enrichmentStatus);
  const key = name.trim().toLowerCase();

  const fdaItem = fdaItems?.find((f) => f.query?.toLowerCase() === key);
  const pndfItem = pndfItems?.find((p) => p.name?.toLowerCase() === key);

  const resolveStatus = (item: { found: boolean } | undefined): VerificationState => {
    if (!item) return isTerminal ? "not_found" : "pending";
    return item.found ? "verified" : "not_found";
  };

  if (!fdaItems && !pndfItems) return { fda: "none", pndf: "none" };
  return {
    fda: fdaItems ? resolveStatus(fdaItem) : "none",
    pndf: pndfItems ? resolveStatus(pndfItem) : "none",
  };
};

// ─── sub-components ──────────────────────────────────────────────────────────

const VerificationChip = ({ label, state }: { label: string; state: VerificationState }) => {
  if (state === "none") return null;

  const styles: Record<VerificationState, string> = {
    verified: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    not_found: "bg-rose-50 text-rose-600 ring-rose-200",
    pending: "bg-sky-50 text-sky-600 ring-sky-200",
    none: "",
  };

  const Icon = state === "verified" ? CheckCircle2 : state === "not_found" ? XCircle : Clock;

  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 ${styles[state]}`}>
      <Icon className="h-2.5 w-2.5" />
      {label}
    </span>
  );
};

const needsReview = (med?: Medication) => (med?.flags ?? []).length > 0;

const DetailGrid = ({ med }: { med: Medication }) => {
  const stats = [
    { key: "quantity", label: "Quantity", value: med.quantity, Icon: Package },
    { key: "frequency", label: "Frequency", value: med.frequency, Icon: Repeat },
  ].filter((f) => !!f.value);

  if (!med.signa && stats.length === 0) return null;

  return (
    <div className="mt-3 space-y-2.5">
      {med.signa && (
        <div className="flex items-start gap-2.5 rounded-lg bg-primary/5 px-3 py-2.5">
          <Pill className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.07em] text-primary/70">Directions</p>
            <p className="mt-0.5 text-sm font-medium leading-snug text-foreground">{med.signa}</p>
          </div>
        </div>
      )}
      {stats.length > 0 && (
        <div className="grid grid-cols-2 gap-2">
          {stats.map(({ key, label, value, Icon }) => (
            <div key={key} className="flex min-w-0 items-center gap-2 rounded-lg border bg-background/60 px-3 py-2">
              <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
              <div className="min-w-0">
                <p className="text-[10px] font-semibold uppercase tracking-[0.07em] text-muted-foreground/70">{label}</p>
                <p className="break-words text-sm font-medium text-foreground">{value}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// ─── prescription meta strip ─────────────────────────────────────────────────

const PrescriptionMeta = ({ results }: { results: PrescriptionResponse }) => {
  const items = [
    { label: "Age", value: results.patient_age, Icon: User },
    { label: "Sex", value: results.patient_sex, Icon: User },
  ].filter((i) => !!i.value);
  if (items.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-x-6 gap-y-2 rounded-xl border bg-card/80 px-4 py-3">
      {items.map(({ label, value, Icon }) => (
        <div key={label} className="flex min-w-0 items-center gap-2">
          <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.07em] text-muted-foreground/60">{label}</p>
            <p className="text-sm font-medium text-foreground">{value}</p>
          </div>
        </div>
      ))}
    </div>
  );
};

// ─── medication card ──────────────────────────────────────────────────────────

interface MedicationCardProps {
  index: number;
  displayName: string;
  med?: Medication;
  verification: DrugVerification;
}

const MedicationCard = ({ index, displayName, med, verification }: MedicationCardProps) => {
  const hasVerification = verification.fda !== "none" || verification.pndf !== "none";
  const flagged = needsReview(med);

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.16, delay: Math.min(index * 0.05, 0.25), ease: [0.16, 1, 0.3, 1] }}
    >
      <div
        className={`rounded-xl border bg-card px-4 py-3.5 shadow-sm ${
          flagged ? "border-amber-300/70 bg-amber-50/30" : ""
        }`}
      >
        <div className="flex items-start gap-3">
          <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-muted text-[11px] font-semibold tabular-nums text-muted-foreground">
            {index + 1}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
              <h4 className="break-words text-base font-semibold leading-snug text-foreground">{displayName}</h4>
              <div className="flex shrink-0 items-center gap-1.5">
                {flagged && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700 ring-1 ring-amber-200">
                    <AlertTriangle className="h-2.5 w-2.5" />
                    Needs review
                  </span>
                )}
                {hasVerification && (
                  <>
                    <VerificationChip label="FDA" state={verification.fda} />
                    <VerificationChip label="PNDF" state={verification.pndf} />
                  </>
                )}
              </div>
            </div>
            {med?.dosage && (
              <p className="mt-0.5 font-mono text-sm text-muted-foreground">{med.dosage}</p>
            )}
          </div>
        </div>

        <div className="pl-9">
          {med && <DetailGrid med={med} />}

          {!med?.dosage && !med?.quantity && !med?.frequency && !med?.signa && (
            <p className="mt-2 text-xs text-muted-foreground">No details extracted.</p>
          )}

          {med?.match_method && (
            <p className="mt-2.5 text-[10px] text-muted-foreground/50">via {med.match_method}</p>
          )}
        </div>
      </div>
    </motion.div>
  );
};

const buildCopyText = (meds: { name: string; medication?: Medication }[]) =>
  meds
    .map(({ name, medication: m }, i) =>
      [
        `${i + 1}. ${toDisplayName(name)}${m?.dosage ? ` ${m.dosage}` : ""}`,
        m?.signa && `   Directions: ${m.signa}`,
        m?.quantity && `   Quantity: ${m.quantity}`,
        m?.frequency && `   Frequency: ${m.frequency}`,
      ]
        .filter(Boolean)
        .join("\n"),
    )
    .join("\n\n");

// ─── main component ───────────────────────────────────────────────────────────

interface ResultsScreenProps {
  onScanAnother: () => void;
  scanResults: PrescriptionResponse;
}

const ResultsScreen = ({ onScanAnother, scanResults }: ResultsScreenProps) => {
  const [isRawTextOpen, setIsRawTextOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const enrichmentStatus = (scanResults.enrichment_status ?? "").trim().toLowerCase();

  const filteredMedications = (scanResults.medications ?? []).filter((m) => {
    const n = m.name?.trim().toLowerCase() ?? "";
    return n.length > 0 && n !== "unable to parse medications";
  });

  const fallbackMedications =
    filteredMedications.length === 0 ? derivePossibleMedications(scanResults.raw_text) : [];
  const medicationsFromScan =
    filteredMedications.length > 0 ? filteredMedications : fallbackMedications;
  const isUsingFallback = filteredMedications.length === 0 && fallbackMedications.length > 0;

  const medicationMap = new Map<string, { name: string; medication?: Medication }>();
  medicationsFromScan.forEach((med) => {
    const key = normalizeMedicationKey(med.name);
    if (!key || medicationMap.has(key)) return;
    medicationMap.set(key, { name: med.name, medication: med });
  });
  const medicationsToDisplay = Array.from(medicationMap.values());

  const count = medicationsToDisplay.length;
  const reviewCount = medicationsToDisplay.filter((m) => needsReview(m.medication)).length;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(buildCopyText(medicationsToDisplay));
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="space-y-3 pb-1">

      {/* Summary */}
      <div className="flex items-center justify-between gap-3 rounded-xl border bg-card/80 px-4 py-3">
        <div className="flex items-center gap-3">
          <span className="grid h-9 w-9 place-items-center rounded-full bg-emerald-50 text-emerald-600 ring-1 ring-emerald-200">
            <CheckCircle2 className="h-5 w-5" />
          </span>
          <div>
            <p className="text-sm font-semibold text-foreground">
              {count === 0 ? "No medications found" : count === 1 ? "1 medication found" : `${count} medications found`}
            </p>
            {reviewCount > 0 && (
              <p className="text-xs text-amber-700">
                {reviewCount === 1 ? "1 needs review" : `${reviewCount} need review`}
              </p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {isUsingFallback && (
            <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700 ring-1 ring-amber-200">
              Fallback parsing
            </span>
          )}
          {count > 0 && (
            <Button type="button" variant="outline" size="sm" onClick={handleCopy} className="h-8 gap-1.5 bg-card/70">
              {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              {copied ? "Copied" : "Copy"}
            </Button>
          )}
        </div>
      </div>

      {/* Prescription header */}
      <PrescriptionMeta results={scanResults} />

      {/* Empty state */}
      {count === 0 ? (
        <div className="rounded-xl border bg-card/80 px-5 py-8 text-center">
          <AlertCircle className="mx-auto mb-3 h-7 w-7 text-muted-foreground/40" />
          <p className="text-sm font-medium text-foreground">No medications detected</p>
          <p className="mt-1 text-xs text-muted-foreground">Try a clearer image or different framing.</p>
        </div>
      ) : (
        <div className="space-y-2">
          <AnimatePresence>
            {medicationsToDisplay.map((item, index) => {
              const verification = getVerification(
                item.name,
                enrichmentStatus,
                scanResults.fda_verification,
                scanResults.pndf_enriched ?? scanResults.enriched_medications ?? scanResults.enriched,
              );
              return (
                <MedicationCard
                  key={normalizeMedicationKey(item.name) || `med-${index}`}
                  index={index}
                  displayName={toDisplayName(item.name)}
                  med={item.medication}
                  verification={verification}
                />
              );
            })}
          </AnimatePresence>
        </div>
      )}

      {/* Review notes */}
      {scanResults.demo && scanResults.demo.reviewNotes.length > 0 && reviewCount > 0 && (
        <div className="flex items-start gap-2.5 rounded-xl border border-amber-200 bg-amber-50/60 px-4 py-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
          <div className="space-y-1 text-sm text-amber-900">
            <p className="font-semibold">Check against the image</p>
            {scanResults.demo.reviewNotes.map((note) => (
              <p key={note} className="text-xs leading-relaxed text-amber-900/80">{note}</p>
            ))}
          </div>
        </div>
      )}

      {/* Raw OCR collapsible */}
      {scanResults.raw_text && (
        <Collapsible open={isRawTextOpen} onOpenChange={setIsRawTextOpen}>
          <CollapsibleTrigger className="flex w-full items-center justify-between rounded-lg border bg-card/60 px-4 py-3 text-left transition-colors hover:bg-muted/20">
            <div className="flex items-center gap-2">
              <FileText className="h-3.5 w-3.5 text-muted-foreground/60" />
              <span className="text-xs font-semibold text-muted-foreground">{scanResults.demo ? "Transcription" : "Raw OCR text"}</span>
            </div>
            <ChevronDown
              className={`h-3.5 w-3.5 text-muted-foreground/60 transition-transform duration-200 ${
                isRawTextOpen ? "rotate-180" : ""
              }`}
            />
          </CollapsibleTrigger>
          <CollapsibleContent>
            <pre className="mt-1 max-h-48 overflow-auto rounded-lg border bg-muted/25 p-3 text-xs font-mono leading-relaxed whitespace-pre-wrap text-foreground/70">
              {scanResults.raw_text}
            </pre>
          </CollapsibleContent>
        </Collapsible>
      )}

      {/* Action */}
      <Button
        size="lg"
        onClick={onScanAnother}
        variant="outline"
        className="w-full bg-card/70 font-medium"
      >
        <Scan className="mr-2 h-4 w-4" />
        Scan Another Prescription
      </Button>
    </div>
  );
};

export default ResultsScreen;
