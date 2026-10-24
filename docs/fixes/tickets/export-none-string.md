# Empty link exported as the text `None` (`export-none-string`)

**Where:** `editor/utilities.py` `spec_item_to_export`, `spec_item_ref` fields (links such as `Type`, `Kind` target,
p_link/s_link labels). Affects the spec-item CSV export.

**Problem:** an item without a link exports the Python string `None` instead of an empty cell.

**Before / after:**

    ...|None|...   (before)
    ...||...       (after)

**Import:** both forms import the same (the importer turns an unknown reference, including `None`, into no
link). Old files keep importing.

**Check in consumer scripts:** code that tests `cell == 'None'` to mean "no link" must also accept an empty cell.
