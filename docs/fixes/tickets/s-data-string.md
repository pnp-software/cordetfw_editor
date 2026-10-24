# New items store `s_data` as the JSON string `"{}"` (`s-data-string`)

**Where:** `editor/forms.py` `clean_s_data`: a missing `s_data` becomes the string `'{}'`, which the JSONField stores as
the JSON *string* `"{}"` instead of the empty object `{}`.

**Export effect:** `s_data` is exported (project ZIP `spec_items.csv`), so the cell differs:

    ...,"""{}""",...   (string, today)        ...,{},...   (object, after the fix)

**Options (to decide):**
1. Fix for new items only (one line, `return {}`); existing rows keep `"{}"` -> mixed data, exports of old and new
   items differ.
2. Option 1 plus a data migration converting existing `"{}"` rows to `{}` (changes stored data and the export of
   every affected item once).
3. Leave as is.

**Import:** the ZIP importer must accept both forms (see `import-project-s-data-double-encoded`, track K Task 7.4).

**Check in consumer scripts:** code reading `s_data` from `spec_items.csv` must accept `{}` as well as `"{}"`.
