# Spec-item CSV exports `Value` references as internal ids (`export-eval-ref-raw`)

**Where:** `editor/utilities.py` `spec_item_to_export`. Affects the spec-item CSV export
(`export_spec_items`, format CSV) of categories with an `eval_ref` field: DataItem and EnumValue, column `Value`.

**Problem:** text fields (`ref_text`) are exported in edit form (`#DataItem:Dom:Calc`), but `Value` is exported in
database form (`#iref:107`). The number is the database id of the target item, so the file is not portable: imported
into another project (or another installation) the reference points to an unrelated item or is dangling.

**Before / after** (row from `tests/golden/export/spec_items/di_project.csv`):

    Dom|Calc|Title of Calc||#iref:107 * 2||| ...              (before)
    Dom|Calc|Title of Calc||#DataItem:<domain>:<name> * 2||| ... (after: category, domain and name of item 107)

**Import:** the CSV importer copies `Value` as-is today, so it must also convert `#Cat:domain:name` back to
`#iref:N` (as it does for `ref_text`), and keep accepting `#iref:N` from old files. Old files then import as
today. A new file imported by the *current* release would keep the text `#DataItem:<domain>:<name>` unconverted
(forward-incompatible): deploy before exchanging new files.

**Check in consumer scripts:** anything that parses `Value` for `#iref:<n>` (e.g. to evaluate or resolve
values) must accept `#<Cat>:<domain>:<name>`.

**Not affected:** project ZIP export (already converts), LaTeX export.
