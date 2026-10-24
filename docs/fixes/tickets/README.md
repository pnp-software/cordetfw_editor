# Export-change tickets (track K, decision open)

Each fix below changes the bytes of an export. None is implemented until the operator approves it
(decision 2026-10-24: undecided; tickets written so they can be filed on GitHub and used to check the
scripts that read these exports). Every ticket states the exact change, so a consumer script can be
tested against a "before" and an "after" file.

| Ticket | Export | Change |
|---|---|---|
| [export-eval-ref-raw](export-eval-ref-raw.md) | spec-item CSV | `Value` references `#iref:N` -> `#Cat:domain:name` |
| [export-none-string](export-none-string.md) | spec-item CSV | empty link `None` -> empty cell |
| [export-dangling-ref-literal](export-dangling-ref-literal.md) | spec-item CSV, project ZIP, LaTeX | `ERROR:N` for a deleted reference target |
| [export-filename-not-escaped](export-filename-not-escaped.md) | spec-item CSV / LaTeX download | HTTP `Content-Disposition` header only |
| [csv-formula-injection](csv-formula-injection.md) | spec-item CSV, project ZIP | cells starting with `= + - @` |
| [latex-export-injection](latex-export-injection.md) | LaTeX export | `\ { } $` escaped |

Common rule for all of them: exports made by the current release must still import with the same result
(checked by `tests/test_compat_corpus.py`); an approved change gets an entry in
`docs/fixes/expected-diffs.json`.
