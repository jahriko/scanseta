---
version: 1
slug: "frontend-src-pages-index-tsx"
primary_target: "frontend/src/pages/Index.tsx"
related_targets: ["frontend/src/components/ResultsScreen.tsx","frontend/src/components/ProcessingScreen.tsx"]
---

# Scanseta scan workspace

Scope: the whole single-page app (upload, processing, results, error) in `frontend/src/pages/Index.tsx` and its screens. Mode: Operate.
Audience: pharmacists at a Philippine pharmacy counter checking a handwritten prescription. Task: read the extracted medicines against the photo, see what needs a human look, copy the list.
Constraints: demo mode must always work; patient name, prescriber and date stay hidden; existing `npm run verify:demo` labels stay.
Pinned by the user (2026-10-28): "Like a real app", reference Linear; the familiar lab-sheet/carton/label hand was "too plain".

## Direction contract

THESIS: A Linear-grade work tool for reading prescriptions: a dark ink sidebar, a bright light work area, and every medicine a crisp list row with a status glyph. Refuses the category default of soft white cards with a blue accent and pill badges.
OWN-WORLD: Ink sidebar (#15171c) with teal selection; bright work area (#fbfbfc) with 1px hairline dividers (#e6e7ea), no cards; Inter at 13 to 15px with tabular figures; one teal accent (#0f8a73) for primary actions, focus and progress; amber for review, red for not found.
STORY: The pharmacist picks or uploads a prescription, watches a scan line pass over the photo while steps fill, then reads a dense medicine list beside the image in the order it was written (the image is the source of truth), spots the amber-tinted rows that need review, and copies the list.
FIRST VIEWPORT: Left 248px ink sidebar: wordmark, New scan, sample prescriptions list with thumbnails, Demo/Live switch and backend status at the foot. Main: 48px top bar with breadcrumb and status; below it the photo canvas fills the left, a 440px review pane on the right with the heading, a count line, and medicine rows. Primary action (Upload) centred in the empty canvas.
FORM: Pinned Linear-style product shell (user steer over the roll), Scanseta teal; signature move is the pie status glyph that fills from empty to complete for scan steps and medicine verification. seed:b2897aa791abf2ba
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
