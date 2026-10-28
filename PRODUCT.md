# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Pharmacists and pharmacy staff in the Philippines who receive handwritten doctor's prescriptions at the counter. Their job is to read each prescription correctly, confirm what medicine, strength, quantity and directions were written, and catch anything unclear before dispensing.

## Product Purpose
Scanseta reads a photo of a handwritten prescription and turns it into a structured list of medications (name, strength, quantity, frequency, directions). In live mode it also checks each medicine against the Philippine FDA register and the Philippine National Drug Formulary (PNDF). Success is a pharmacist trusting the list enough to use it as a second reader, while still seeing exactly which items need a human look.

## Positioning
A vision-language model fine-tuned on Philippine handwritten prescriptions (Qwen2.5-VL with the `scanseta/qwen_prescription_model` adapter), paired with lookups against Philippine sources (FDA PH, PNDF). Built and deployed at the University of the Immaculate Conception (scanseta.uic.edu.ph).

## Operating Context
Used at a pharmacy counter or desk, on a desktop browser or a phone camera. A pharmacist uploads or photographs the prescription, waits a few seconds, then compares the extracted list against the image side by side. Local abbreviations (OD, BID, TID, q4h, Sig, #) and brand names (Biogesic) appear as written.

## Capabilities and Constraints
- Two modes: Demo (prepared results for eight bundled sample prescriptions, no backend) and Live (real model on a backend reached through `VITE_API_BASE_URL`, currently a GPU PC behind a Cloudflare tunnel).
- Input: upload an image, capture with the camera (live only), or pick a sample.
- Output: medication list with review flags, FDA/PNDF verification chips that fill in while validation runs, raw transcription, copy-to-clipboard.
- Patient name, prescriber and date are deliberately not shown; only age and sex.
- Live model load takes minutes; the backend may be offline, so demo mode must always work.
- Stack: Vite + React + TypeScript + Tailwind + shadcn/ui, deployed on Vercel from `master` (pushes to master go live).

## Brand Commitments
The app should feel like a real, polished product tool, with Linear as the stated reference (user, 2026-10-28). Generic "plain" health-app styling was rejected.

## Evidence on Hand
Eight real sample prescription images in `frontend/public/demo-prescriptions/` with prepared transcriptions in `frontend/src/lib/demo-prescriptions.ts`. No accuracy benchmarks, user counts or testimonials exist; do not invent any.

## Product Principles
- The image is the source of truth; the extracted list is a second reading, never a replacement.
- Uncertainty is shown, never hidden: unclear names, missing strengths and unverified drugs are flagged plainly.
- Nothing is guessed: no inferred active ingredients or concentrations.
- Fast at the counter: the result must be readable at a glance and copyable.

## Accessibility & Inclusion
Readable in bright pharmacy lighting and on phones; status must never rely on colour alone.
