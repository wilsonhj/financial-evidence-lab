# Excerpts

Per the methodology, up to 10 fixtures detected with `nested_tables` receive
a verbatim byte-slice excerpt (< 50 KB) here.

**This directory is intentionally empty of excerpts.** Across all 60 selected
primary documents, `nested_tables` was detected in **zero** filings: every
document has a maximum `<table>` nesting depth of exactly 1 (tables are flat
siblings, each closing before the next opens — verified by a balanced-tag
scan of the fetched bytes). No fixture qualifies for a `nested_tables`
excerpt, so none was written. See the top-level `README.md` status section.
