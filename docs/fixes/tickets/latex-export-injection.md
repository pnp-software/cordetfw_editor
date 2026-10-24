# LaTeX commands pass through the LaTeX export (`latex-export-injection`)

**Where:** `editor/convert.py` `frmt_string` (escapes `% & # ^ ~ _` and newlines, but not `\ { } $`),
`editor/utilities.py` `spec_item_to_latex` (`NVal` not escaped at all).

**Problem:** item text such as `\input{/etc/passwd}` or `\write18{...}` reaches the generated `.csv`/LaTeX data
unchanged. Dangerous only for whoever compiles the document with shell-escape enabled or in a directory with
sensitive files; also an ordinary `$` or `{` in text can break the LaTeX build.

**Possible fix:** escape `\` -> `\textbackslash{}`, `{` -> `\{`, `}` -> `\}`, `$` -> `\$`, and apply `frmt_string`
to `NVal`.

**Before / after:**

    Cost in $ with \input{x}   ->   Cost in \$ with \textbackslash{}input\{x\}

**Cost:** anyone who deliberately writes LaTeX in item text (math `$x^2$`, `\textbf{}`) gets it printed literally.
Before deciding, count items in the production dump whose text contains `\`, `$`, `{` (aggregate scan, no data
committed).

**Import:** not affected (the LaTeX export is not importable).

**Check in consumer scripts:** the LaTeX document templates that `\input` these files; build them with a
before/after export and compare the PDF.
