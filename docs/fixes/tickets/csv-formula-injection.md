# Spreadsheet formula injection in CSV exports (`csv-formula-injection`)

**Where:** `editor/utilities.py` (spec-item CSV), `editor/resources.py` (project ZIP CSVs).

**Problem:** a cell starting with `=`, `+`, `-` or `@` is executed as a formula when the CSV is opened in
Excel/LibreOffice (e.g. `=HYPERLINK(...)`, DDE). Any project writer can put such text into an item; the victim is
whoever opens the export in a spreadsheet.

**Possible fix:** prefix such cells with `'`.

**Before / after:**

    ...|- first point|...    (before)
    ...|'- first point|...   (after)

**Cost:** many item texts are markdown lists (`- item`), so a large number of cells would change. The importer
must strip the prefix again, otherwise a round trip adds `'` to the text; old files (no prefix) keep importing.
A text that really starts with `'` becomes ambiguous unless it is also escaped.

**Alternative:** no byte change; document "open exports with formula evaluation off / import as text".

**Check in consumer scripts:** every script reading text columns would see the leading `'` and must strip it.
