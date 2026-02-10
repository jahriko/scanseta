# ScanSeta Backend - Conceptual Technical Documentation

## Overview

ScanSeta is a backend service that turns prescription images into a usable list of medication names, then optionally verifies and enriches those names using authoritative sources. The backend is designed as a **hybrid system**:

- A **vision-language model** handles noisy, real-world prescription images.
- A **deterministic post-processing layer** improves reliability and consistency.
- **Verification/enrichment modules** attach reference data for downstream workflows.

## What the backend produces

At a high level, a scan returns:

- The model's extracted medication names (raw and cleaned).
- A canonicalized medication list (when possible).
- Flags/indicators when an extracted token is uncertain or out-of-vocabulary.
- Optional verification/enrichment results from external sources.

## Core components

### 1) API layer

The backend exposes endpoints that conceptually support:

- Scanning a **single** prescription image.
- Scanning a **batch** of prescription images.
- Enriching/verifying a **manual list** of drug names (without scanning an image).

### 2) Model inference (image -> candidate drug names)

The model step is responsible for:

- Reading the prescription image.
- Producing a simple medication-name output (a list of candidate drug tokens).

The system intentionally keeps this model output lightweight so downstream logic can enforce consistency and safety rules.

### 3) Token cleaning and normalization

Before any matching or enrichment, extracted text is normalized so that:

- Extraneous artifacts (dosage numbers, units, schedules, formatting noise) do not pollute the medication-name list.
- Duplicate tokens are removed.
- The output becomes stable enough to compare against a reference lexicon and external sources.

### 4) Post-processing (canonicalization + quality signals)

Post-processing improves the model output by:

- Matching tokens against a curated lexicon (to correct common misspellings and normalize variants).
- Computing plausibility/quality signals for each token.
- Assigning flags to indicate uncertainty (for example, unknown tokens or improbable strings).

This step is the main quality-control layer: it makes the downstream verification/enrichment more accurate and reduces wasted lookups.

### 5) Verification and enrichment

When there are eligible medication names, the backend can attach reference data from two conceptual sources:

- **Verification**: confirm whether a medication appears in the FDA verification portal (primary signal).
- **Enrichment**: retrieve medication reference information from the PNDF (secondary detail source).

Enrichment is typically skipped for tokens that post-processing marks as unreliable.

### 6) Cache-first design

Verification/enrichment is designed to be cache-first:

- Previously retrieved results are reused to reduce latency and external dependence.
- Live lookups are only performed when necessary.

This makes the service more robust and predictable in real-world deployments where external sites may be slow, rate-limited, or intermittently unavailable.

## Operational behavior (conceptual)

- On startup, the service loads the model so that scan requests can be served immediately.
- The service may also perform background warming/refreshing of reference data caches.
- On shutdown, external resources used for verification/enrichment are cleaned up.

## How to extend the backend (conceptual)

Common extension points include:

- Improving the model prompt/output format (while keeping post-processing stable).
- Expanding the lexicon and refining matching/flagging rules.
- Adding additional verification sources or integrating a structured drug database.
- Evolving the response schema to include richer structured extraction (dose, frequency, etc.) once the model and parsing support it reliably.

