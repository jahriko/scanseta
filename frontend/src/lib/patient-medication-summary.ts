import { PNDFEnrichmentItem } from "./prescription-api";

export interface PatientSummarySection {
  title: string;
  bullets: string[];
}

export interface PatientMedicationSummary {
  sections: PatientSummarySection[];
}

const MAX_SECTION_BULLETS = 3;
const MAX_BULLET_LENGTH = 180;

const INTERACTION_HINTS: Array<{ keyword: string; label: string }> = [
  { keyword: "warfarin", label: "Warfarin or other blood thinners" },
  { keyword: "alcohol", label: "Alcohol" },
  { keyword: "carbamazepine", label: "Carbamazepine" },
  { keyword: "phenobarbital", label: "Phenobarbital and related seizure medicines" },
  { keyword: "isoniazid", label: "Isoniazid" },
  { keyword: "probenecid", label: "Probenecid" },
];

const normalizeText = (value?: string | null): string => {
  if (!value) {
    return "";
  }
  return value
    .replace(/\s+/g, " ")
    .replace(/\s*;\s*/g, "; ")
    .replace(/\s*,\s*/g, ", ")
    .trim();
};

const shorten = (value: string, maxLength = MAX_BULLET_LENGTH): string => {
  if (value.length <= maxLength) {
    return value;
  }

  const stopAtComma = value.lastIndexOf(",", maxLength);
  const stopAtSpace = value.lastIndexOf(" ", maxLength);
  const cutoff = Math.max(stopAtComma, stopAtSpace);

  if (cutoff <= 0) {
    return `${value.slice(0, maxLength - 3).trim()}...`;
  }

  return `${value.slice(0, cutoff).trim()}...`;
};

const simplifyPhrase = (value: string): string =>
  shorten(
    value
      .replace(/\[[^\]]+\]/g, "")
      .replace(/\bpyrexia\b/gi, "fever")
      .replace(/\bhepatic\b/gi, "liver")
      .replace(/\brenal\b/gi, "kidney")
      .replace(/\bby mouth\b/gi, "orally")
      .replace(/\s+/g, " ")
      .trim(),
  );

const toSentenceCase = (value: string): string =>
  value.length > 1 ? value.charAt(0).toUpperCase() + value.slice(1) : value.toUpperCase();

const splitNarrative = (value?: string | null): string[] => {
  const text = normalizeText(value);
  if (!text) {
    return [];
  }

  return text
    .split(/(?<=[.;])\s+|\s*;\s*/)
    .map((part) => part.trim().replace(/^[\-*]\s*/, ""))
    .filter((part) => part.length > 0)
    .map((part) => part.replace(/[.;]\s*$/, "").trim());
};

const unique = (values: string[]): string[] => {
  const seen = new Set<string>();
  const result: string[] = [];
  values.forEach((item) => {
    const key = item.toLowerCase();
    if (!seen.has(key)) {
      seen.add(key);
      result.push(item);
    }
  });
  return result;
};

const summarizeList = (value?: string | null, maxItems = MAX_SECTION_BULLETS): string[] =>
  unique(splitNarrative(value))
    .slice(0, maxItems)
    .map((entry) => toSentenceCase(simplifyPhrase(entry)));

const extractMaximumDoseGuidance = (dosage?: string | null): string[] => {
  const text = normalizeText(dosage).toLowerCase();
  if (!text) {
    return [];
  }

  const matches = Array.from(text.matchAll(/(maximum[^.;)]{0,120})/gi)).map((match) =>
    toSentenceCase(match[1].trim()),
  );

  return unique(matches)
    .slice(0, 2)
    .map((entry) => simplifyPhrase(entry));
};

const extractAudienceGuidance = (dosage?: string | null): string[] => {
  const text = normalizeText(dosage).toLowerCase();
  if (!text) {
    return [];
  }

  const bullets: string[] = [];
  if (text.includes("adult")) {
    bullets.push("Adult dosing guidance is available in PNDF.");
  }
  if (text.includes("child") || text.includes("infant") || text.includes("pediatric")) {
    bullets.push("Child dosing is weight-based and should follow age/weight guidance.");
  }
  if (text.includes("pregnan")) {
    bullets.push("Ask your doctor before use during pregnancy.");
  }

  return bullets.slice(0, MAX_SECTION_BULLETS);
};

const extractTopInteractions = (interactions?: string | null): string[] => {
  const text = normalizeText(interactions).toLowerCase();
  if (!text) {
    return [];
  }

  const hits = INTERACTION_HINTS.filter((item) => text.includes(item.keyword)).map((item) => item.label);
  return unique(hits).slice(0, MAX_SECTION_BULLETS);
};

const extractDangerSigns = (item?: PNDFEnrichmentItem): string[] => {
  const text = `${normalizeText(item?.precautions)} ${normalizeText(item?.adverse_reactions)}`.toLowerCase();
  if (!text.trim()) {
    return [];
  }

  const warnings: string[] = [];
  if (text.includes("anaphylaxis") || text.includes("hypersensitivity")) {
    warnings.push("Severe allergy signs (swelling, breathing trouble, widespread rash).");
  }
  if (text.includes("liver") || text.includes("hepatic")) {
    warnings.push("Possible liver injury signs (yellow eyes/skin, dark urine, severe nausea).");
  }
  if (text.includes("overdose")) {
    warnings.push("Any overdose concern, especially if multiple medicines contain this drug.");
  }

  return warnings.slice(0, MAX_SECTION_BULLETS);
};

const extractHowToTake = (item?: PNDFEnrichmentItem): string[] => {
  const directions = summarizeList(item?.administration, 2);
  const dose = summarizeList(item?.dosage_instructions, 1);
  return unique([...dose, ...directions]).slice(0, MAX_SECTION_BULLETS);
};

const section = (title: string, bullets: string[]): PatientSummarySection | null => {
  const normalized = unique(
    bullets
      .map((bullet) => bullet.trim())
      .filter((bullet) => bullet.length > 0)
      .map((bullet) => toSentenceCase(simplifyPhrase(bullet))),
  ).slice(0, MAX_SECTION_BULLETS);

  if (normalized.length === 0) {
    return null;
  }

  return { title, bullets: normalized };
};

export const buildPatientMedicationSummary = (
  name: string,
  item?: PNDFEnrichmentItem,
): PatientMedicationSummary => {
  const safeName = name.trim() || "This medicine";
  const sections: PatientSummarySection[] = [];

  const uses = section("What This Medicine Is For", summarizeList(item?.indications));
  if (uses) {
    sections.push(uses);
  }

  const whoCanUse = section("Who Can Use It", extractAudienceGuidance(item?.dosage_instructions));
  if (whoCanUse) {
    sections.push(whoCanUse);
  }

  const howToTake = section("How to Take It (Simple)", extractHowToTake(item));
  if (howToTake) {
    sections.push(howToTake);
  }

  const maxDose = section("Maximum Safe Dose", extractMaximumDoseGuidance(item?.dosage_instructions));
  if (maxDose) {
    sections.push(maxDose);
  }

  const contraindications = section("Do Not Use If", summarizeList(item?.contraindications));
  if (contraindications) {
    sections.push(contraindications);
  }

  const precautions = section("Check With Doctor First", summarizeList(item?.precautions));
  if (precautions) {
    sections.push(precautions);
  }

  const sideEffects = section("Possible Side Effects", summarizeList(item?.adverse_reactions));
  if (sideEffects) {
    sections.push(sideEffects);
  }

  const dangerSigns = section("Danger Signs: Get Help Now", extractDangerSigns(item));
  if (dangerSigns) {
    sections.push(dangerSigns);
  }

  const interactions = section("Medicine Interactions (Top Risk)", extractTopInteractions(item?.drug_interactions));
  if (interactions) {
    sections.push(interactions);
  }

  const reminders = section("Quick Reminders", [
    `Check all labels so you do not double-dose ${safeName.toLowerCase()}.`,
    "Ask a pharmacist before combining this with cold, pain, or flu products.",
    "This summary is educational and does not replace medical advice.",
  ]);
  if (reminders) {
    sections.push(reminders);
  }

  return { sections };
};
