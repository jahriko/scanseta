import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Scan, FileText, AlertCircle, ChevronDown, User, UserCheck, Calendar, CheckCircle2, XCircle, Clock } from "lucide-react";
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

const DetailGrid = ({ med }: { med: Medication }) => {
  const fields = [
    { key: "dosage", label: "Dosage", value: med.dosage },
    { key: "quantity", label: "Qty", value: med.quantity },
    { key: "frequency", label: "Frequency", value: med.frequency },
    { key: "signa", label: "Signa", value: med.signa },
  ].filter((f) => !!f.value);

  if (fields.length === 0) return null;

  return (
    <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2">
      {fields.map(({ key, label, value }) => (
        <div key={key} className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-[0.07em] text-muted-foreground/70">{label}</p>
          <p className="mt-0.5 font-mono text-sm font-medium text-foreground">{value}</p>
        </div>
      ))}
    </div>
  );
};

// ─── prescription meta strip ─────────────────────────────────────────────────

const PrescriptionMeta = ({ results }: { results: PrescriptionResponse }) => {
  const hasAny = results.patient_name || results.patient_age || results.patient_sex || results.doctor_name || results.date;
  if (!hasAny) return null;

  return (
    <div className="rounded-lg bg-muted/40 px-4 py-3">
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        {results.patient_name && (
          <div className="flex items-center gap-1.5 min-w-0">
            <User className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase tracking-[0.07em] text-muted-foreground/60">Patient</p>
              <p className="text-sm font-medium text-foreground truncate">{results.patient_name}</p>
            </div>
          </div>
        )}
        {results.patient_age && (
          <div className="flex items-center gap-1.5 min-w-0">
            <User className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase tracking-[0.07em] text-muted-foreground/60">Age</p>
              <p className="text-sm font-medium text-foreground">{results.patient_age}</p>
            </div>
          </div>
        )}
        {results.patient_sex && (
          <div className="flex items-center gap-1.5 min-w-0">
            <User className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase tracking-[0.07em] text-muted-foreground/60">Sex</p>
              <p className="text-sm font-medium text-foreground">{results.patient_sex}</p>
            </div>
          </div>
        )}
        {results.doctor_name && (
          <div className="flex items-center gap-1.5 min-w-0">
            <UserCheck className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase tracking-[0.07em] text-muted-foreground/60">Prescriber</p>
              <p className="text-sm font-medium text-foreground truncate">{results.doctor_name}</p>
            </div>
          </div>
        )}
        {results.date && (
          <div className="flex items-center gap-1.5 min-w-0">
            <Calendar className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase tracking-[0.07em] text-muted-foreground/60">Date</p>
              <p className="text-sm font-medium text-foreground">{results.date}</p>
            </div>
          </div>
        )}
      </div>
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

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.16, delay: Math.min(index * 0.05, 0.25), ease: [0.16, 1, 0.3, 1] }}
    >
      <div className="rounded-xl border bg-card/90 px-4 py-3.5 shadow-sm">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-baseline gap-2 min-w-0">
            <span className="shrink-0 text-[11px] font-semibold tabular-nums text-muted-foreground/50">
              {String(index + 1).padStart(2, "0")}
            </span>
            <h4 className="break-words text-base font-semibold leading-snug text-foreground">{displayName}</h4>
          </div>
          {hasVerification && (
            <div className="flex shrink-0 items-center gap-1.5 pt-0.5">
              <VerificationChip label="FDA" state={verification.fda} />
              <VerificationChip label="PNDF" state={verification.pndf} />
            </div>
          )}
        </div>

        {med && <DetailGrid med={med} />}

        {!med?.dosage && !med?.quantity && !med?.frequency && !med?.signa && (
          <p className="mt-2 text-xs text-muted-foreground">No details extracted.</p>
        )}

        {med?.match_method && (
          <p className="mt-2.5 text-[10px] text-muted-foreground/50">via {med.match_method}</p>
        )}
      </div>
    </motion.div>
  );
};

// ─── main component ───────────────────────────────────────────────────────────

interface ResultsScreenProps {
  onScanAnother: () => void;
  scanResults: PrescriptionResponse;
}

const ResultsScreen = ({ onScanAnother, scanResults }: ResultsScreenProps) => {
  const [isRawTextOpen, setIsRawTextOpen] = useState(false);

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

  return (
    <div className="space-y-3 pb-1">

      {/* Prescription header */}
      <PrescriptionMeta results={scanResults} />

      {/* Count row */}
      <div className="flex items-center justify-between px-0.5">
        <p className="text-xs font-semibold uppercase tracking-[0.07em] text-muted-foreground">
          {count === 0 ? "No medications" : count === 1 ? "1 medication" : `${count} medications`}
        </p>
        {isUsingFallback && (
          <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700 ring-1 ring-amber-200">
            Fallback parsing
          </span>
        )}
      </div>

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

      {/* Raw OCR collapsible */}
      {scanResults.raw_text && (
        <Collapsible open={isRawTextOpen} onOpenChange={setIsRawTextOpen}>
          <CollapsibleTrigger className="flex w-full items-center justify-between rounded-lg border bg-card/60 px-4 py-3 text-left transition-colors hover:bg-muted/20">
            <div className="flex items-center gap-2">
              <FileText className="h-3.5 w-3.5 text-muted-foreground/60" />
              <span className="text-xs font-semibold text-muted-foreground">Raw OCR text</span>
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
