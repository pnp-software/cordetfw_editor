# Known issues: forms, convert, markdown, ref_filters, utilities (pinned by tests/test_forms.py, tests/test_convert.py, tests/test_utilities.py)

These behaviours are pinned as-is by the characterization suite and must be fixed
only after the Django upgrade, in separate changes. Each id appears as `# KNOWN-ISSUE: <id>`
next to the asserting test.

| id | where | current behaviour |
|----|-------|-------------------|
| `appform-cats-substring` | editor/forms.py:88 | `ApplicationForm.clean_cats` tests `cat in self.project.cats` on the project's comma-separated STRING, so any substring of it is accepted: `Item` (of `DataItem`), `Enum`, `Type,Value`, and even the empty string (`DataItem,,EnumType`, trailing comma). |
| `help-double-space` | editor/forms.py:38 | `ProjectForm` category help text is built from `predefined_cats` (already `', '`-joined) and then `replace(',', ', ')` again, giving two spaces after every comma (`ParReq,  DerReq,  ...`). The validation error message is correct (single space). |
| `s-data-string` | editor/forms.py:234 | `SpecItemForm.clean_s_data` replaces a missing `s_data` (None) with the string `'{}'`, not an empty dict (a posted JSON object stays a dict). |
| `enum-value-no-type` | editor/configs.py:128 | `do_cat_specific_checks` for a DataItem of enumerated type dereferences `enum_val.s_link.id`; a referenced EnumValue without an `s_link` raises `AttributeError` (HTTP 500) instead of a form error. |
| `dataitem-no-plink` | editor/configs.py:118 | `do_cat_specific_checks` dereferences `cd['p_link'].cat` for every DataItem; a `None` `p_link` raises `AttributeError` (and a missing key `KeyError`). Not reachable through `SpecItemForm` today because `p_link` is required for DataItem, but the function is unguarded. |
| `ref-link-backslash` | editor/convert.py:75, editor/templatetags/ref_filters.py:99,107 | Internal reference links end in `.../0\list_spec_items` (backslash from an unescaped `'\l'`). Also listed in `views.md`; pinned here at unit level for `convert_db_to_display` and `disp_trac`. (The `spec_item_ref` links built in `conv_db_disp_spec_item_ref` use a correct `/`.) |
| `md-no-escape` | editor/markdown.py (`markdown_to_html`, `markdown_to_latex`) | No escaping of HTML or LaTeX in the markdown functions; `<script>` and `&` pass through unchanged. Nesting of emphasis markers (`**a ++b++ c**`) is not supported, emphasis does not span lines, and a bullet list at the very start of the text loses its first item (the pattern requires a preceding newline). |
| `xss-display` | editor/convert.py:78-91 (`convert_db_to_display`) | Only the link parts (domain, name, title attributes) are escaped; all other text of the field is returned raw (docstring claims it is safe). Stored HTML/JS in descriptions is rendered as is. |
| `xss-tag` | editor/templatetags/ref_filters.py (`conv_db_disp`) | Every value is wrapped in `mark_safe` without escaping (e.g. a title `<script>1</script>` is emitted verbatim). `filter_expand_tip` and `disp_trac` also mark unescaped values safe. |
| `conv-date-nameerror` | editor/convert.py:110-112 (`conv_db_disp_date`) | Body is `return s` with `s` undefined: `NameError`. Mapped from kind `date` in `ref_filters.conv_db_disp_func` (no category uses it today). |
| `exp-ref-no-dots` | editor/convert.py:20 (`pattern_ref_exp`) | The export-representation pattern accepts only `[a-zA-Z0-9_]`, so `a.b:c` or `a-b:c` (valid identifiers) cannot be imported as `spec_item_ref` links: `convert_exp_to_db` returns `None`. `convert_exp_to_db` also returns `None` for ambiguous `domain:name` (same pair in two categories). |
| `disp-trac-plink-none` | editor/templatetags/ref_filters.py:93 | `disp_trac` evaluates `link.p_link.application_id` before the `None` check on `link.p_link`: a trac link (e.g. VerLink) without `p_link` raises `AttributeError` (HTTP 500 on the list page). |
| `export-eval-ref-raw` | editor/utilities.py:91-107 (`spec_item_to_export`) | `eval_ref` fields (DataItem/EnumValue `Value`) are exported in db form (`#iref:N`) while `ref_text` fields are exported in edit form (`#Cat:dom:name`); a round trip into another project keeps dangling `#iref:N`. |
| `export-none-string` | editor/utilities.py:100 | An empty `spec_item_ref` (None) is exported as the string `None`. |
| `owner-empty-names` | editor/utilities.py:145 | `get_user_choices(project)` always renders the project owner as `name (first last)`, i.e. `alice ( )` when the owner has no names; all other users are rendered without parentheses in that case. A user with only one of first/last name gets `dave (Dave )`. |
| `redirect-int-parent` | editor/utilities.py:224,231 | `get_redirect_url` concatenates `s_parent_id`/`p_parent_id` into the URL and so requires strings (as taken from the GET query); an int raises `TypeError`. |
| `make-temp-dir-nameerror` | editor/utilities.py:317 | The `OSError` handler of `make_temp_dir` references undefined `request` and `exp_dir`: any failure to create the directory (missing parent, directory exists) raises `NameError` instead of returning `''` as documented (callers in views.py test for `''`). |

Other observations pinned (not defects per se)

- `snake_to_camel('')` returns `'_'`.
- Substituting an `#iref:N` in `render_for_eval` inserts the referenced value without parentheses (`#iref:y*2` with y=`2*3+1` evaluates to `8.0`, not `14.0`).
- `eval_di_value` returns `str(float)` (`'14.0'`); invalid expressions and unresolved references return the input string unchanged.
- Duplicate domain:name checks in `SpecItemForm.clean` rely on the DB collation: SQLite (baseline test DB) is case-sensitive, MySQL (production) is not. Tests pin the SQLite behaviour; the self-exclusion (`exclude(id=item_id)`) that makes a case-only rename acceptable on MySQL cannot be exercised on SQLite.
- A `ValidationError` raised in the eval_ref check aborts `SpecItemForm.clean` before the duplicate-name check, so only the first problem is reported.
