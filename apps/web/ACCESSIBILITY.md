# Accessibility audit — Observatory and reader

Manual audit against the WCAG 2.2 AA success criteria that apply to this
document-style web app (Search Observatory + evidence reader). Every
component, page, and `globals.css` was read; contrast ratios below are
computed from the actual CSS custom-property colours (relative-luminance
formula, `(L1+0.05)/(L2+0.05)`), not estimated.

Status legend: **Pass** (already conformant, no change needed), **Fixed in
this change** (audit found a real gap; fixed as part of this PR), **N/A**
(criterion's trigger condition doesn't occur in this app), **Open**
(acknowledged gap, not fixed here — reason given).

| Criterion | Status | Notes / files |
|---|---|---|
| 1.3.1 Info and Relationships | Pass | Heading order is `h1` (site header, `layout.tsx`) → `h2` (page/section headings) → `h3`/`h4` (`DocumentPane.tsx` `headingLevel()`, nested subsections in `ObservatoryTrace.tsx`) with no level skipped. Data tables have a `<caption>` and `scope="col"`/`scope="row"` (`FactPanel.tsx` `DuplicateComparison`, `ObservatoryTrace.tsx` `BudgetSection`/`LaneSection`, `RunComparison.tsx`). Landmarks are labelled and distinct (`aria-label`/`aria-labelledby` on `<nav>`, `<main>`, `<aside>`, `<section>` throughout `EvidenceReader.tsx` and `ObservatoryTrace.tsx`). Form groups use `<fieldset>`/`<legend>` (`ObservatoryControls.tsx` "Lanes"). |
| 1.4.3 Contrast (Minimum) | Pass | `--color-text` `#1a2330` on `--color-bg` `#ffffff`: 15.82:1. `--color-muted` `#55637a` on white: 6.08:1, on `--color-surface` `#f6f7f9`: 5.68:1, on `--color-highlight-bg` `#fff3c2`: 5.46:1 — all above the 4.5:1 (normal text) floor. `--color-accent` `#1f4e8c` on white: 8.31:1. `--color-warning-text` `#7a1a14` on `--color-warning-bg` `#fdeaea`: 9.13:1. `--color-ok-border` on `--color-ok-bg`: 5.78:1. All pass with margin; see `apps/web/src/app/globals.css`. |
| 1.4.11 Non-text Contrast | Fixed in this change | `--color-border` `#d4d9e0` is only ~1.4:1 against white/surface — well under the 3:1 floor required for the visual boundary of a UI *component* (as opposed to a merely decorative container rule). Interactive-control borders that relied on it — `ObservatoryControls.tsx` text/number/datetime inputs and the "Lanes" `fieldset`, and `NotesPanel.tsx`'s note `textarea` — now use a new `--color-border-strong` (`#6b7789`, ~4.5:1 on white and surface). Plain decorative container borders (`.panel-card`, `.fact-card`, table rules) are unchanged: they're not "user interface components" under 1.4.11. See `globals.css`. |
| 2.1.1 Keyboard | Pass | Every actionable element is a native `<button>`, `<a>`, or form control — no click-only `<div>`s. `OutlineNav.tsx` implements a roving-tabindex listbox (ArrowUp/Down/Home/End) per the ARIA APG. Span citations (`DocumentPane.tsx`) are real `<button>`s, natively focusable and Enter/Space-activatable (see `reader-a11y.test.tsx`). Server-action forms (`RerunButton.tsx`, `FeedbackControl.tsx`, `ObservatoryControls.tsx`) submit natively. |
| 2.4.3 Focus Order | Pass | DOM order matches reading/visual order everywhere: skip link → site header → (page heading →) outline nav → document pane → evidence panel (`EvidenceReader.tsx`'s `.reader-layout` is a 3-column grid whose DOM order is outline/document/panel, matching the visual left-to-right layout). No `tabIndex` values reorder focus outside 0/-1 (roving tabindex only, in `OutlineNav.tsx`). |
| 2.4.7 Focus Visible | Pass | Global `:focus-visible { outline: 3px solid var(--color-accent); outline-offset: 2px; }` in `globals.css` applies to every focusable element (no component overrides `outline: none`). Outline colour contrast: `#1f4e8c` on white is 8.31:1, comfortably over the 3:1 non-text-contrast floor for focus indicators. |
| 2.4.11 Focus Not Obscured (Minimum) | Pass | No fixed/sticky element overlaps another in a way that could hide a focused control: `.site-header` is in normal flow (not sticky/fixed); `.outline-nav` and `.evidence-panel` are `position: sticky` but sit in separate grid columns beside the scrolling document, not stacked on top of it. |
| 2.5.8 Target Size (Minimum) | Fixed in this change | Two standalone (non-inline) controls rendered under 24×24 CSS px: the notes-list "Remove" `<button>` had horizontal-only padding (`padding: 0 0.4rem`, ~18px tall) — now `padding: 0.4rem` plus explicit `min-width`/`min-height: 24px`. The unclassed `<button type="submit">Send</button>` in `FeedbackControl.tsx` relied on browser-default button chrome (~20px tall) — `globals.css` now has an explicit `.obs-feedback button` rule with a 24px floor. The `.candidate-ref` reader-deep-link, the sole content of its table cell (not a link inline within a sentence, so the SC's "inline" exception doesn't apply), is now `display: inline-block; padding: 0.2rem 0` to clear 24px. `DocumentPane.tsx`'s `.span-mark` citation buttons stay under 24px tall by design but qualify for the **inline exception**: they are inline `<button>`s inside flowing `<p className="section-content">` text, sized by the surrounding paragraph's line-height. `.outline-item`, `.retry-button`, `.note-form button`, and native checkboxes were already ≥24px or are browser-default controls exempted from author styling. |
| 3.2.1 On Focus | Pass | No component changes context (navigates, submits, or opens anything) purely on focus; all navigation/submission is on click/Enter/Space activation. |
| 3.2.2 On Input | Pass | No `onChange` triggers navigation or submission; `ObservatoryControls.tsx`'s inputs and `NotesPanel.tsx`'s textarea only update local state until an explicit submit. |
| 3.2.3 Consistent Navigation | Pass | The site header, skip link, and page chrome come from the single shared `layout.tsx` and appear identically positioned on every route. |
| 3.2.4 Consistent Identification | Pass | Repeated components have one consistent look/label across pages: `.retry-button` styling and copy pattern is reused for "Rerun…", "Run query", "Try again"; `.badge-ok`/`.badge-warning`/`.badge-info` carry the same colour+glyph+text convention in both the reader (`FactPanel.tsx`) and Observatory (`ObservatoryTrace.tsx`). |
| 3.2.6 Consistent Help | N/A | The app has no help/contact mechanism (no "Contact us", chat, or help link) to be inconsistent about. |
| 4.1.2 Name, Role, Value | Pass | Toggle controls expose state: span citations use `aria-pressed` (`DocumentPane.tsx`), the active outline entry uses `aria-current="true"` (the correct "current item in a set", not a toggle — `OutlineNav.tsx`). Every form control has a programmatic label (`<label htmlFor>`, including visually-hidden labels for the feedback `<select>`/reason `<input>` in `FeedbackControl.tsx`). Landmarks and regions are named via `aria-label`/`aria-labelledby` throughout. |
| 4.1.3 Status Messages | Fixed in this change (reader) / Pass (Observatory) | **Observatory**: query/rerun/feedback submission is a server action that redirects to a new URL carrying `?error=…` or `?feedback=recorded`; the destination page renders that outcome with `role="alert"` (failures) or `role="status"` (feedback recorded) at initial paint (`app/observatory/runs/[runId]/page.tsx`, `ObservatoryControls.tsx`, `ObservatoryTrace.tsx`'s run-state banner) — a full navigation, so the new page's content (including the status banner) is what the browser/AT encounters. **Reader**: adding/removing an analyst note (`NotesPanel.tsx`) is a client-side state change with *no* navigation and no focus move — previously nothing announced the outcome to a screen-reader user not focused on the notes list. `NotesPanel.tsx` now carries a visually-hidden `role="status" aria-live="polite"` region set to "Note added."/"Note removed." on each action. |

## Regression coverage

- `apps/web/src/components/reader-a11y.test.tsx` — added a status-messages
  assertion for the new `NotesPanel` live region (1.4.11/2.5.8 CSS changes
  are covered in the Observatory suite below since they're both exercised
  from `globals.css`; the reader also renders `.note-list button` and
  benefits from the same rule).
- `apps/web/src/components/observatory-a11y.test.tsx` — added assertions
  that `globals.css` uses `--color-border-strong` on interactive-control
  borders (1.4.11) and that `.note-list button` / `.obs-feedback button`
  carry an explicit `min-height: 24px` (2.5.8).
- `apps/web/src/components/NotesPanel.test.tsx` — added assertions that the
  live region markup is present, and that add/remove actions call the
  announcement setter with the expected text.
