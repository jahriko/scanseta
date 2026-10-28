import type { Medication, PrescriptionResponse } from "./prescription-api";

interface DemoPrescription {
  fileName: string;
  sha256: string;
  medications: Omit<Medication, "confidence">[];
  rawText: string;
  reviewNotes: string[];
}

export const demoPrescriptions: DemoPrescription[] = [
  {
    fileName: "RX000005.jpg",
    sha256: "1843fb485521600617268074cb832b8937c7ccf45145dae81cd1231d3eacd42c",
    medications: [{ name: "Amlodipine", dosage: "5 mg", quantity: "30 tablets", frequency: "OD", signa: "1 tab OD" }],
    rawText: "Amlodipine 5 mg #30\nSig: 1 tab OD",
    reviewNotes: ["Prepared from the handwriting. The abbreviation OD is preserved as written."],
  },
  {
    fileName: "RX002290.jpg",
    sha256: "0efdb7ec57a6c042db35951845613d84501944bf9b0554b1172bbc00a3129ffe",
    medications: [{ name: "Atorvastatin", dosage: "40 mg", quantity: "10 tablets", frequency: "OD", signa: "1 tab OD" }],
    rawText: "Atorvastatin 40 mg #10\nSig: 1 tab OD",
    reviewNotes: ["Prepared reading of the handwritten strength and quantity; review against the image."],
  },
  {
    fileName: "RX002335.jpg",
    sha256: "015d28445d36cd20a38f313c0ff37b40551af6cc8ca2b396f63e08e1f1ad4ed3",
    medications: [
      { name: "Metronidazole", dosage: "500 mg/tablet", quantity: "15 tablets", frequency: "3x a day", signa: "1 tablet, 3x a day for 5 days" },
      { name: "Ciprofloxacin", dosage: "500 mg/tablet", quantity: "6 tablets", frequency: "2x a day", signa: "1 tablet, 2x a day for 3 days" },
      { name: "Unclear medication (review needed)", quantity: "9 tablets", frequency: "3x a day", signa: "1 tablet, 3x a day for 3 days", flags: ["REVIEW_REQUIRED"] },
    ],
    rawText: "Metronidazole [brand unclear] 500 mg/tablet #15\nSig: 1 tablet, 3x a day for 5 days\n\nCiprofloxacin 500 mg/tablet #6\nSig: 1 tablet, 2x a day for 3 days\n\n[Third medication name unclear] tablet #9\nSig: 1 tablet, 3x a day for 3 days",
    reviewNotes: ["The first brand name and the third medication name are unclear. The third medication's strength is not shown. No active ingredient has been guessed for it."],
  },
  {
    fileName: "RX002336.jpg",
    sha256: "16292003fc3b3a261907a3e3d240199ed1dc6b5ed631f228495c6a5945c27256",
    medications: [{ name: "Paracetamol (Biogesic)", dosage: "500 mg/tablet", quantity: "12 tablets", frequency: "q4h or as needed", signa: "Take 1 tab q4h or as needed" }],
    rawText: "Biogesic 500 mg/tab\n(Paracetamol) #12\nSig: take 1 tab q4h or as needed",
    reviewNotes: ["The directions are a prepared transcription of the sample, not dosing advice."],
  },
  {
    fileName: "RX002340.jpg",
    sha256: "b6161bdf655451cabec67c2a714b6248e2e17863c9338795b8c36fe7fdbfeccd",
    medications: [
      { name: "Salbutamol syrup", frequency: "3x a day", signa: "1.2 ml, 3x a day for 5 days", flags: ["REVIEW_REQUIRED"] },
      { name: "Salinase nasal spray", frequency: "4x a day (uncertain)", signa: "1-2 sprays per nostril, 4x a day (uncertain)", flags: ["REVIEW_REQUIRED"] },
    ],
    rawText: "[Image read sideways]\nSalbutamol syrup [brand unclear]\n1.2 ml, 3x a day for 5 days\n\nSalinase nasal spray\n1-2 sprays per nostril, 4x a day [uncertain]",
    reviewNotes: ["The syrup concentration is not readable. The nasal spray directions are uncertain and need review. Patient details have not been transcribed."],
  },
  {
    fileName: "RX002347.jpg",
    sha256: "2693cadab844327a8f7ffcf2d19a38610150a7601c8dec3009ec53dcd59a46b5",
    medications: [{ name: "Salbutamol nebulizer", quantity: "50 nebules", frequency: "Every 12 hours", signa: "1 neb every 12 hours", flags: ["REVIEW_REQUIRED"] }],
    rawText: "Salbutamol neb #50\nSig: 1 neb every 12 hours",
    reviewNotes: ["The sample does not specify the strength. No concentration has been inferred."],
  },
  {
    fileName: "RX002359.jpg",
    sha256: "fae56743d5509823d788fa9251eef27ea5338e8be9b1e606800b50df053e9223",
    medications: [{ name: "Amoxicillin", dosage: "500 mg", quantity: "21", frequency: "3x a day", signa: "3x a day for 7 days", flags: ["REVIEW_REQUIRED"] }],
    rawText: "Amoxicillin 500 mg #21\n3x a day for 7 days",
    reviewNotes: ["The number of units per administration is not clearly written, so it has not been filled in."],
  },
  {
    fileName: "RX002364.png",
    sha256: "ebf2e428cf41dfb48b6e41141369abbacbfda2ff0b56dc0cef6cc85c77a18275",
    medications: [{ name: "Cefalexin", dosage: "500 mg/capsule", quantity: "28 capsules", frequency: "Every 6 hours", signa: "1 capsule every 6 hours for 7 days", flags: ["REVIEW_REQUIRED"] }],
    rawText: "Cefalexin 500 mg/cap #28\n1 capsule every 6 hours for 7 days",
    reviewNotes: ["This image is low resolution. The prepared drug name, strength and quantity need review against the original."],
  },
];

export const DEMO_DURATION_MS = 2200;

export const simulatePrescription = async (file: File): Promise<PrescriptionResponse> => {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  const sha256 = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  const sample = demoPrescriptions.find((item) => item.sha256 === sha256);
  if (!sample) {
    throw new Error("No prepared result for this image. Choose a demo prescription or upload an unchanged copy of one of the samples.");
  }

  await new Promise<void>((resolve) => setTimeout(resolve, DEMO_DURATION_MS));

  return {
    success: true,
    processing_time: DEMO_DURATION_MS / 1000,
    medications: sample.medications.map((medication) => ({ ...medication, confidence: 0 })),
    raw_text: sample.rawText,
    can_enrich: false,
    enrichment_status: "disabled",
    enrichment_message: "Demo mode: no live FDA or PNDF checks were performed.",
    demo: { kind: "prepared", sample: sample.fileName, reviewNotes: sample.reviewNotes },
  };
};
