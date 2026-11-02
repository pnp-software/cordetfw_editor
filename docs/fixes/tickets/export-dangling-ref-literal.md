# Reference to a deleted item exported as `ERROR:N` (`export-dangling-ref-literal`)

**Where:** `editor/convert.py` `convert_db_to_edit` / `convert_db_to_latex`. Affects text fields with `#iref:N` whose
target item no longer exists: spec-item CSV, project ZIP (`spec_items.csv`), LaTeX export.

**Problem:** the reference is written as `ERROR:9999`. On re-import this is plain text, so the information that it
was a reference is lost, and the text `ERROR:9999` ends up in the item.

**Options (to decide):**
1. keep `ERROR:N` (document it; no byte change);
2. export a recognisable marker, e.g. `#missing:9999`, that the importer reports as "dangling reference" and drops
   or keeps as text;
3. export nothing for the dangling reference.

**Before / after** (option 2, `tests/golden/export/spec_items/di_project.csv`):

    ... dangling ERROR:9999 ...      (before)
    ... dangling #missing:9999 ...   (after)

**Import:** old files with `ERROR:N` still import as text (unchanged).

**Check in consumer scripts:** anything searching for `ERROR:` to detect broken references.
Production dump 2026-10-21: 11 dangling `#iref` in total, 3 in live items.
