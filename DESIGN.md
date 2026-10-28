---
name: Scanseta
description: A Linear-grade work tool that reads handwritten Philippine prescriptions into a checkable medicine list.
colors:
  scanseta-teal: "hsl(168 80% 29%)"
  ink-sidebar: "hsl(228 14% 9%)"
  ink-raised: "hsl(228 12% 15%)"
  ink-hairline: "hsl(228 12% 17%)"
  ink-text: "hsl(228 10% 70%)"
  ink-text-strong: "hsl(0 0% 98%)"
  ink-teal: "hsl(166 64% 52%)"
  work-bright: "hsl(240 14% 99%)"
  surface-white: "hsl(0 0% 100%)"
  canvas-grey: "hsl(228 12% 95%)"
  wash: "hsl(228 12% 96%)"
  hover-wash: "hsl(228 12% 94%)"
  hairline: "hsl(228 10% 90%)"
  field-stroke: "hsl(228 10% 86%)"
  ink-text-body: "hsl(228 12% 11%)"
  slate-muted: "hsl(228 7% 40%)"
  review-amber: "hsl(32 92% 33%)"
  review-tint: "hsl(40 100% 96%)"
  not-found-red: "hsl(0 68% 47%)"
  verified-green: "hsl(152 62% 32%)"
typography:
  headline:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.55
    letterSpacing: "-0.015em"
    fontFeature: "\"cv11\", \"ss01\", \"ss03\""
  title:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1.375
    letterSpacing: "-0.01em"
    fontFeature: "\"cv11\", \"ss01\", \"ss03\""
  body:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.375
    fontFeature: "\"cv11\", \"ss01\", \"ss03\""
  ui:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: "\"cv11\", \"ss01\", \"ss03\""
  label:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.33
    fontFeature: "\"cv11\", \"ss01\", \"ss03\", \"tnum\""
  caption:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: "11px"
    fontWeight: 500
    lineHeight: 1.45
  data:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1.5
    fontFeature: "\"tnum\""
  data-sm:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.33
rounded:
  thumb: "3px"
  sm: "4px"
  md: "6px"
  lg: "8px"
  xl: "12px"
  full: "9999px"
spacing:
  hair: "2px"
  xs: "6px"
  sm: "10px"
  md: "12px"
  row: "14px"
  gutter: "20px"
  canvas: "32px"
  topbar: "48px"
  sidebar: "248px"
  review-pane: "440px"
components:
  button-primary:
    backgroundColor: "{colors.scanseta-teal}"
    textColor: "{colors.surface-white}"
    typography: "{typography.ui}"
    rounded: "{rounded.md}"
    padding: "0 14px"
    height: "36px"
  button-primary-lg:
    backgroundColor: "{colors.scanseta-teal}"
    textColor: "{colors.surface-white}"
    rounded: "{rounded.md}"
    padding: "0 20px"
    height: "40px"
  button-outline:
    backgroundColor: "{colors.surface-white}"
    textColor: "{colors.ink-text-body}"
    typography: "{typography.ui}"
    rounded: "{rounded.md}"
    padding: "0 14px"
    height: "36px"
  button-outline-hover:
    backgroundColor: "{colors.wash}"
  button-compact:
    backgroundColor: "{colors.surface-white}"
    textColor: "{colors.ink-text-body}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "0 10px"
    height: "28px"
  button-ghost-hover:
    backgroundColor: "{colors.hover-wash}"
    textColor: "{colors.ink-text-body}"
  sidebar-item:
    backgroundColor: "{colors.ink-sidebar}"
    textColor: "{colors.ink-text}"
    rounded: "{rounded.md}"
    padding: "6px 8px"
  sidebar-item-active:
    backgroundColor: "{colors.ink-raised}"
    textColor: "{colors.ink-text-strong}"
  mode-switch:
    backgroundColor: "{colors.ink-raised}"
    textColor: "{colors.ink-text}"
    rounded: "{rounded.md}"
    padding: "2px"
    height: "32px"
  top-bar:
    backgroundColor: "{colors.work-bright}"
    textColor: "{colors.ink-text-body}"
    typography: "{typography.ui}"
    height: "48px"
    padding: "0 20px"
  medicine-row:
    backgroundColor: "{colors.work-bright}"
    textColor: "{colors.ink-text-body}"
    padding: "14px 20px"
  medicine-row-review:
    backgroundColor: "{colors.review-tint}"
  status-glyph:
    size: "16px"
  transcription-block:
    backgroundColor: "{colors.wash}"
    textColor: "{colors.ink-text-body}"
    typography: "{typography.data-sm}"
    rounded: "{rounded.md}"
    padding: "12px 14px"
---

# Design System: Scanseta

## Overview

**Creative North Star: "The Second Reader"**

Scanseta is a work tool that sits beside the prescription and reads it a second time. The photo is the authority; the interface is the quiet colleague next to it, laying out what it read as a dense, ordered list and pointing plainly at what it could not read. The world is a Linear-style product shell, pinned by the user: an ink sidebar that holds navigation and samples, a bright work area for counter lighting, and content divided by 1px hairlines instead of boxed in cards.

Density is high and calm. Text runs 11 to 15px with one 18px headline for the empty state; weight and tracking carry hierarchy, not size jumps. Color is almost absent from the work area so that the few signals that appear (teal for action and progress, amber for "look again", red for "not found", green for "verified") read at a glance. Every status is drawn by a single glyph family, the pie StatusGlyph, which differs in shape as well as color.

Motion is short and functional: a teal scan line sweeps the photo while it is read, pies fill as steps complete, rows settle in with a 4px rise. All looping motion stops under reduced-motion.

**Key Characteristics:**
- Ink sidebar (248px) beside a bright work area; 48px top bar with breadcrumb.
- Photo canvas left, 440px review pane right on desktop; stacked on mobile.
- Hairline-divided list rows, no cards, no drop-shadowed panels.
- Inter for interface, JetBrains Mono for data (RX ids, strengths, transcription).
- One teal accent; amber, red and green reserved for status.
- The pie StatusGlyph is the signature: one glyph family for every state.

## Colors

A near-monochrome cool-grey world with one teal voice and three status hues. Tokens are HSL triples in `frontend/src/index.css`, consumed by Tailwind; HSL is canonical.

### Primary
- **Scanseta Teal** (`scanseta-teal`): primary buttons, focus rings, the progress bar, the scan line, the in-progress pie, text selection tint (18%). Nothing decorative.
- **Ink Teal** (`ink-teal`): the lighter teal used only on the ink sidebar: the brand mark tile, the sidebar focus ring, and the "model loaded" status dot. It exists because Scanseta Teal is too dark to read on ink.

### Neutral
- **Ink Sidebar** (`ink-sidebar`): the sidebar and the mobile top strip.
- **Ink Raised** (`ink-raised`): active sample row, hovered rows (60%), the mode-switch track, thumbnail placeholders.
- **Ink Hairline** (`ink-hairline`): the divider above the sidebar foot.
- **Ink Text** (`ink-text`) and **Ink Text Strong** (`ink-text-strong`): resting and active/heading text on the sidebar.
- **Work Bright** (`work-bright`): the work-area background. Bright on purpose for pharmacy counter lighting.
- **Surface White** (`surface-white`): outline buttons and the few raised surfaces (camera panel).
- **Canvas Grey** (`canvas-grey`): the photo canvas behind the prescription image, and the empty dropzone at 50%.
- **Wash** (`wash`) and **Hover Wash** (`hover-wash`): progress track, transcription block, upload icon tile; ghost hover.
- **Hairline** (`hairline`): every divider and border in the work area.
- **Field Stroke** (`field-stroke`): outline-button stroke, the dashed dropzone edge, scrollbar thumbs.
- **Ink Text Body** (`ink-text-body`): primary text in the work area.
- **Slate Muted** (`slate-muted`): secondary text, meta lines, breadcrumb parents (5.9:1 on Work Bright).

### Status
- **Review Amber** (`review-amber`): the review glyph, "needs review" signals, the review notice border (25%), the "model not loaded" dot.
- **Review Tint** (`review-tint`): the full-width background of a medicine row that needs review, and of the review notice band.
- **Not-Found Red** (`not-found-red`): the "missing" glyph, "not found" verification text, the configuration-error notice (5% fill, 20% ring).
- **Verified Green** (`verified-green`): the "done" glyph only. It is a status green, distinct from Scanseta Teal; never use it for actions.

### Named Rules
**The One Voice Rule.** Teal is the only non-status color, and it means "act here" or "working". It never decorates, fills a heading, or tints a section.

**The Status Tints Rows Rule.** A row that needs review is tinted edge to edge with Review Tint; it is not boxed, badged, or bordered.

**The Amber Is a Signal Rule.** Review Amber is reserved for the review state: glyphs, borders, tints and the short "needs review" words. It is set dark enough (about 4.8:1 on Review Tint) for small text; never lighten it.

## Typography

**Display Font:** none; the system has no display tier.
**Body Font:** Inter (with system-ui, sans-serif), stylistic sets `cv11`, `ss01`, `ss03`.
**Label/Mono Font:** JetBrains Mono (with ui-monospace, monospace).

**Character:** Inter at small sizes with tight tracking reads as a dense, precise tool; JetBrains Mono marks anything that is data to be checked against the paper. Inter is a deliberate choice, kept because the user pinned Linear as the reference, not a default left in place.

### Hierarchy
- **Headline** (600, 18px, -0.015em): the empty-state heading only.
- **Title** (600, 15px, -0.01em): pane headings and medicine names.
- **Body** (400, 14px, snug): directions (signa) under a medicine name; empty-state explanation (max 24rem, balanced).
- **UI** (400 or 500, 13px): the working size. Breadcrumb, count line, buttons, step labels, notices.
- **Label** (400, 12px, tabular): meta facts under a row, step timings, compact buttons.
- **Caption** (500, 11px): sidebar section header, sample summaries, backend status.
- **Data** (JetBrains Mono 500, 13px, tabular): medicine strength, right-aligned in the row.
- **Data Small** (JetBrains Mono 400, 12px): RX sample ids, raw transcription, inline code.

### Named Rules
**The Mono Means Data Rule.** JetBrains Mono is used only for values a pharmacist checks against the paper or a system: strengths, RX ids, transcription, config values. Labels and prose stay in Inter.

**The Tabular Figures Rule.** Every number that can change or be compared (progress %, quantities, step timings, strengths) uses tabular figures.

**The Small And Tight Rule.** Hierarchy comes from weight (400/500/600) and tracking, inside an 11 to 18px range. No size above 18px in the product shell.

## Layout

Desktop (from 1024px) is a fixed-height app shell: a 248px ink sidebar, then a column with a 48px top bar (breadcrumb, status, compact action) and the work area. With a scan open, the work area splits into a photo canvas (flexible, Canvas Grey, image contained and centred with 24px inset) and a 440px review pane divided from it by a hairline. Without a scan, the work area holds a centred empty state inside a dashed 12px-radius dropzone with 32px outer padding.

Below 1024px the sidebar collapses into an ink top strip with the mode switch; the canvas stacks above the review pane (minimum 42vh) and samples move into a 2-column grid (4 columns from 640px) below the empty state.

Spacing rhythm: 20px horizontal gutter in the review pane and top bar, 14px vertical padding in medicine rows, 10px in step rows, 12px column gap between glyph, text and value, 6px between inline meta items and icon-label pairs. The review pane scrolls on its own; the canvas does not.

### Named Rules
**The Image Beside The List Rule.** On desktop the photo and the extracted list are always visible side by side; the list never replaces or covers the image.

## Elevation & Depth

Flat. Depth comes from the ink/bright split, Canvas Grey behind the photo, and hairlines. Shadows are limited to a 1-2px contact edge on buttons and the active mode-switch segment, plus the scan-line glow.

### Shadow Vocabulary
- **Teal contact** (`box-shadow: 0 1px 2px hsl(168 80% 15% / 0.25)`): primary buttons.
- **Neutral contact** (`box-shadow: 0 1px 2px hsl(228 20% 20% / 0.06)`): outline buttons.
- **Ink segment** (`box-shadow: 0 1px 2px rgba(0,0,0,0.3)`): selected mode-switch segment on the sidebar.
- **Scan glow** (`box-shadow: 0 0 0 1px hsl(var(--primary) / 0.15), 0 6px 18px hsl(var(--primary) / 0.35)`): the moving scan line only.

### Named Rules
**The Hairline Not Card Rule.** Group with 1px Hairline dividers (`divide-y` plus top and bottom rule) and full-bleed rows. Panels do not float on shadows.

## Shapes

Small, consistent corners. Controls and inline surfaces use 6px; the brand mark and upload icon tile use 8px; the empty dropzone uses 12px; sample thumbnails use 3px; the mode-switch segment uses 5px inside its 6px track. Full rounding is for the 6px status dots and the progress bar. List rows and bands have no radius: they run edge to edge between hairlines.

The recurring geometry is the circle of the StatusGlyph: a 16px outlined ring that fills.

## Components

### Buttons
Quiet and compact, Linear-weight.
- **Shape:** gently rounded (6px).
- **Primary:** Scanseta Teal fill, white 13px medium text, 36px tall with 14px side padding (40px and 20px at large), teal contact shadow. One per view: Upload in the empty state.
- **Outline:** white fill, Field Stroke border, neutral contact shadow; hover goes to Wash. Used for secondary actions (camera, copy list, scan another).
- **Compact:** 28px outline button with 12px text and 14px icons, for the top bar and the count line.
- **Ghost:** no fill until hover (Hover Wash).
- **Hover / Focus:** 150ms color transitions; focus is a 2px Scanseta Teal ring offset 2px. Disabled drops to 50% opacity.

### Navigation (sidebar)
- **Style:** Ink Sidebar column; 48px header row with the brand mark (22px Ink Teal tile, 6px radius, three ink lines) and the wordmark in 14px semibold.
- **Items:** 32px "New scan" row; sample rows with a 28x32px thumbnail, an RX id in Data Small and a caption summary. Rest is Ink Text; hover is Ink Raised at 60%; active is Ink Raised with Ink Text Strong and `aria-current`.
- **Foot:** hairline above, backend status dot plus caption, and the Demo/Live segmented switch.
- **Top bar:** breadcrumb ("Scans" > file name) in 13px, a status indicator with a StatusGlyph, and a compact action at the right.

### Medicine Row (signature list item)
A three-column grid: 16px StatusGlyph, the medicine content, and the strength right-aligned in Data. Medicine name in Title; directions in Body; a meta line in Label with quantity, frequency and FDA/PNDF verification marks (13px glyph plus text). Missing strength reads "Strength not written" in place of the value. Rows that need review take Review Tint full width. Rows enter with opacity 0 to 1 and a 4px rise over 180ms, `cubic-bezier(0.16, 1, 0.3, 1)`, staggered 40ms up to 200ms.

### StatusGlyph (signature component)
One 16px glyph family for every status in the app, built on a 16-unit viewBox:
- **Todo:** dashed ring (1.5px, dash 2.4/2.2) in muted grey at 60%.
- **Pending:** the same dashed ring in Slate Muted, rotating once every 2.4s.
- **Progress:** solid teal ring with an inner pie that fills clockwise from 12 o'clock by fraction, animating 200ms `cubic-bezier(0.16, 1, 0.3, 1)`.
- **Done:** filled Verified Green disc with a white check.
- **Review:** filled Review Amber disc with a white exclamation.
- **Missing:** filled Not-Found Red disc with a white cross.
Each state differs in shape as well as hue, so color is never the only signal. It labels itself (`role="img"`) only when no visible text sits beside it.

### Processing Steps
A hairline-divided ordered list: StatusGlyph, step label in UI (medium when active), and a tabular timing or "Done" at the right. Above it a 4px fully rounded progress track in Wash with a Scanseta Teal fill and a tabular percentage.

### Scan Line
A 2px Scanseta Teal bar with the scan glow, sweeping the photo top to bottom and back (4% to 96%) every 1.8s on `cubic-bezier(0.65, 0, 0.35, 1)` while a scan runs. Removed under reduced-motion.

### Notices
Full-width or inset bands, not cards: a 13px semibold title and 13px body beside a 16px icon. Review notices use Review Tint with an amber hairline; errors use Not-Found Red at 5% fill with a 20% inset ring; both 6px radius when inset in the empty state, square when they span the review pane.

### Transcription
A collapsible disclosure (13px medium trigger, rotating chevron, 150ms) opening a Wash block in Data Small, 6px radius, capped at 192px with its own scroll.

## Do's and Don'ts

### Do:
- **Do** keep the ink sidebar and bright work area split; new screens live inside this shell.
- **Do** separate list content with 1px Hairline dividers and full-bleed rows.
- **Do** use the StatusGlyph for every status, in place of new badges, chips or icons.
- **Do** put strengths, RX ids and raw text in JetBrains Mono with tabular figures.
- **Do** reserve Scanseta Teal for actions, focus and progress; use Ink Teal on the sidebar.
- **Do** pair every status color with a shape or a word.
- **Do** stop looping motion (scan line, pending spin) under `prefers-reduced-motion`.

### Don't:
- **Don't** wrap content in soft white cards with shadows, or float panels on elevation.
- **Don't** add a second accent hue or use Verified Green for actions.
- **Don't** lighten Review Amber; below about 4.5:1 its small "needs review" text stops being readable on Review Tint.
- **Don't** go above 18px type inside the product shell.
- **Don't** cover or replace the prescription photo with the extracted list.
