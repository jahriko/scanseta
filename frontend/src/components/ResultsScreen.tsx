import { useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, Check, ChevronRight, Copy, FileSearch, ScanLine } from "lucide-react";
import StatusGlyph, { GlyphState } from "@/components/StatusGlyph";
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

const needsReview = (med?: Medication) => (med?.flags ?? []).length > 0;

const verificationText: Record<VerificationState, string> = {
  verified: "found",
  not_found: "not found",
  pending: "checking",
  none: "",
};

const VerificationMark = ({ label, state }: { label: string; state: VerificationState }) => {
  if (state === "none") return null;
  const glyph: GlyphState = state === "verified" ? "done" : state === "not_found" ? "missing" : "pending";
  return (
    <span className="inline-flex items-center gap-1.5">
      <StatusGlyph state={glyph} size={13} />
      <span className={state === "not_found" ? "text-destructive" : undefined}>
        {label} {verificationText[state]}
      </span>
    </span>
  );
};

const rowGlyph = (flagged: boolean, v: DrugVerification): { state: GlyphState; label: string } => {
  if (flagged) return { state: "review", label: "Needs review" };
  if (v.fda === "not_found" || v.pndf === "not_found") return { state: "missing", label: "Not found in a drug register" };
  if (v.fda === "pending" || v.pndf === "pending") return { state: "pending", label: "Verification in progress" };
  if (v.fda === "verified" || v.pndf === "verified") return { state: "done", label: "Verified" };
  return { state: "done", label: "Read" };
};

const PrescriptionMeta = ({ results }: { results: PrescriptionResponse }) => {
  const items = [
    { label: "Age", value: results.patient_age },
    { label: "Sex", value: results.patient_sex },
  ].filter((i) => !!i.value);
  if (items.length === 0) return null;

  return (
    <dl className="flex gap-6 text-[13px]">
      {items.map(({ label, value }) => (
        <div key={label} className="flex gap-1.5">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="font-medium text-foreground">{value}</dd>
        </div>
      ))}
    </dl>
  );
};

interface MedicationRowProps {
  index: number;
  displayName: string;
  med?: Medication;
  verification: DrugVerification;
}

const MedicationRow = ({ index, displayName, med, verification }: MedicationRowProps) => {
  const flagged = needsReview(med);
  const glyph = rowGlyph(flagged, verification);
  const facts = [med?.quantity, med?.frequency].filter(Boolean) as string[];
  const hasAnyDetail = !!(med?.dosage || med?.quantity || med?.frequency || med?.signa);

  return (
    <motion.li
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18, delay: Math.min(index * 0.04, 0.2), ease: [0.16, 1, 0.3, 1] }}
      className={`grid grid-cols-[16px_minmax(0,1fr)_auto] gap-x-3 px-5 py-3.5 ${flagged ? "bg-review-surface" : ""}`}
    >
      <StatusGlyph state={glyph.state} label={glyph.label} className="mt-0.5" />
      <div className="min-w-0">
        <h4 className="break-words text-[15px] font-semibold leading-snug tracking-[-0.01em] text-foreground">{displayName}</h4>
        {med?.signa && <p className="mt-1 text-sm leading-snug text-foreground/85">{med.signa}</p>}
        {(facts.length > 0 || flagged || verification.fda !== "none" || verification.pndf !== "none") && (
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {flagged && <span className="font-medium text-review">Needs review</span>}
            {facts.map((fact) => (
              <span key={fact} className="tnum">{fact}</span>
            ))}
            <VerificationMark label="FDA" state={verification.fda} />
            <VerificationMark label="PNDF" state={verification.pndf} />
          </div>
        )}
        {!hasAnyDetail && <p className="mt-1 text-xs text-muted-foreground">No details extracted.</p>}
        {med?.match_method && <p className="mt-1 text-[11px] text-muted-foreground/80">via {med.match_method}</p>}
      </div>
      <div className="text-right">
        {med?.dosage ? (
          <span className="tnum font-mono text-[13px] font-medium text-foreground">{med.dosage}</span>
        ) : (
          <span className="text-xs text-review">Strength not written</span>
        )}
      </div>
    </motion.li>
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
    <div className="flex flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 pb-3">
        <p className="text-[13px] text-muted-foreground">
          <span className="font-medium text-foreground">
            {count === 0 ? "No medications found" : count === 1 ? "1 medication found" : `${count} medications found`}
          </span>
          {reviewCount > 0 && (
            <span className="text-review"> · {reviewCount === 1 ? "1 needs review" : `${reviewCount} need review`}</span>
          )}
          {isUsingFallback && <span> · Fallback parsing</span>}
        </p>
        {count > 0 && (
          <Button type="button" variant="outline" size="sm" onClick={handleCopy} className="h-7 gap-1.5 px-2.5 text-xs">
            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            {copied ? "Copied" : "Copy list"}
          </Button>
        )}
      </div>

      <div className="px-5 pb-3">
        <PrescriptionMeta results={scanResults} />
      </div>

      {count === 0 ? (
        <div className="mx-5 border-y border-border py-10 text-center">
          <FileSearch className="mx-auto mb-3 h-6 w-6 text-muted-foreground" />
          <p className="text-sm font-medium text-foreground">No medications detected</p>
          <p className="mt-1 text-[13px] text-muted-foreground">Retake the photo with the whole prescription in frame and no glare.</p>
        </div>
      ) : (
        <ul className="divide-y divide-border border-y border-border">
          {medicationsToDisplay.map((item, index) => {
            const verification = getVerification(
              item.name,
              enrichmentStatus,
              scanResults.fda_verification,
              scanResults.pndf_enriched ?? scanResults.enriched_medications ?? scanResults.enriched,
            );
            return (
              <MedicationRow
                key={normalizeMedicationKey(item.name) || `med-${index}`}
                index={index}
                displayName={toDisplayName(item.name)}
                med={item.medication}
                verification={verification}
              />
            );
          })}
        </ul>
      )}

      {scanResults.demo && scanResults.demo.reviewNotes.length > 0 && reviewCount > 0 && (
        <div className="flex gap-2.5 border-b border-review/25 bg-review-surface px-5 py-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-review" />
          <div className="space-y-1">
            <p className="text-[13px] font-semibold text-foreground">Check against the image</p>
            {scanResults.demo.reviewNotes.map((note) => (
              <p key={note} className="text-[13px] leading-relaxed text-foreground/80">{note}</p>
            ))}
          </div>
        </div>
      )}

      {scanResults.raw_text && (
        <Collapsible open={isRawTextOpen} onOpenChange={setIsRawTextOpen} className="mx-5 mt-4">
          <CollapsibleTrigger className="flex w-full items-center gap-1.5 rounded-md py-1.5 text-left text-[13px] font-medium text-muted-foreground transition-colors hover:text-foreground">
            <ChevronRight className={`h-3.5 w-3.5 transition-transform duration-150 ${isRawTextOpen ? "rotate-90" : ""}`} />
            {scanResults.demo ? "Transcription" : "Raw OCR text"}
          </CollapsibleTrigger>
          <CollapsibleContent>
            <pre className="mt-1.5 max-h-48 overflow-auto rounded-md bg-muted px-3.5 py-3 font-mono text-xs leading-relaxed whitespace-pre-wrap text-foreground/80">
              {scanResults.raw_text}
            </pre>
          </CollapsibleContent>
        </Collapsible>
      )}

      <div className="mx-5 mt-5">
        <Button size="lg" onClick={onScanAnother} variant="outline" className="w-full">
          <ScanLine className="h-4 w-4" />
          Scan Another Prescription
        </Button>
      </div>
    </div>
  );
};

export default ResultsScreen;
