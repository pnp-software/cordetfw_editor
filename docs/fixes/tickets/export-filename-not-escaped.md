# Download filename header built by hand (`export-filename-not-escaped`)

**Where:** `editor/views.py` `export_spec_items` (`Content-Disposition` header). File content is **not** changed.

**Problem:** the header is `attachment; filename= "<name>"` (space after `=`), quotes in project/application names
are not escaped, and non-ASCII names are sent in a form browsers do not decode, so the downloaded file gets a
wrong or truncated name.

**Before / after** (project `Proj "X"` / `Prüf`):

    Content-Disposition: attachment; filename= "Proj "X"_DataItem.csv"           (before)
    Content-Disposition: attachment; filename="Proj \"X\"_DataItem.csv"          (after, Django content_disposition_header)
    Content-Disposition: attachment; filename*=utf-8''Pr%C3%BCf_DataItem.csv     (after, non-ASCII)

**Import:** not affected.

**Check in consumer scripts:** only scripts that download through HTTP and parse the header themselves
(e.g. `curl -J`, `wget --content-disposition`, a regex on `filename= "`). Plain ASCII names keep the same
filename, but the header text changes (no space after `=`).
