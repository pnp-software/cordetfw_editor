# Known issues: import/export, FW Profile access, authentication

Pinned by `tests/test_import_export.py`, `tests/test_ext_cats.py`, `tests/test_auth.py`
(grep for `KNOWN-ISSUE: <id>`). Track S/K fixes are marked per row (**FIXED in Task x.y** / **WONTFIX**); see docs/fixes/register.md.

## Import / export

| id | location | current behaviour |
|----|----------|-------------------|
| temp-dir-collision | editor/utilities.py:309-319 | **FIXED in Task 7.2c** (`make_temp_dir` uses `tempfile.mkdtemp` (unique, mode 0700) and returns `''` with the intended message on error). Was: `make_temp_dir` names the directory by timestamp (1 s). A second export/import within the same second hits `OSError`; the handler uses undefined `request` and `exp_dir`, so a `NameError` (HTTP 500) results. |
| temp-dir-not-cleaned | editor/views.py:1097-1150, editor/views.py:1057-1090 | **FIXED in Task 7.2c** (export directories are removed after the response, import directories in a `finally`). Was: Export and import directories (CSV files, zip) are never removed from `temp_dir`. |
| import-project-role-lost | editor/imports.py:169-173 | **FIXED in Task 7.4a** (`ProjectUser.role` is read from `project_users.csv`). Was: `ProjectUser.role` is not read from `project_users.csv`; every user is imported as `RO`. |
| import-project-created-at-lost | editor/imports.py:192-221 | **FIXED in Task 7.4a** (`SpecItem.created_at` is imported from `spec_items.csv`). Was: `SpecItem.created_at` is not imported; it takes the model default `2000-01-01`. |
| import-project-application-version-lost | editor/imports.py:136-140 | **FIXED in Task 7.4a** (`Release.application_version` is imported from `releases.csv`). Was: `Release.application_version` is not imported (always 0). |
| import-project-s-data-double-encoded | editor/imports.py:206 | **FIXED in Task 7.4a** (`s_data` is imported as the JSON value the export wrote; an empty cell is `{}`; old double-encoded text is decoded; known limitation: a stored string that looks like a JSON object/list imports as the object). Was: `s_data` JSON text from the CSV is assigned as a string, so the JSONField stores a JSON string (and `{}` becomes `""`); a re-export yields `"{\"a\": 1}"`. |
| import-project-auto-now-timestamps | editor/imports.py:149-185 | **FIXED in Task 7.4a** (`updated_at` of Project, Application, ValSet and ProjectUser is restored from the export). Was: `updated_at` of Project, Application, ValSet and ProjectUser are `auto_now` fields; the values in the CSV are overwritten by the import time. |
| import-project-crlf-lost | editor/imports.py:20-21,49-51 | **FIXED in Task 7.4a** (the CSV members are opened with `newline=''`, CR LF is kept). Was: Files are opened with `open(..., 'r')` (universal newlines): a CR LF inside a field comes back as LF. |
| import-project-empty-app-cats | editor/imports.py:100-105 | **FIXED in Task 7.4a** (an application with an empty category list is imported). Was: An application with empty `cats` cannot be imported (`''.split(',') == ['']`, not a configured category); message is `The category  in application X is not defined in configs.json`. |
| import-project-not-atomic | editor/imports.py:130-146 | **FIXED in Task 7.4a** (the project import runs in one transaction; on failure one error message and nothing is created). Was: Import is not transactional: a failure after some writes (e.g. unknown release author) leaves the already created Release rows behind. |
| import-project-dangling-link-crash | editor/imports.py:228-241 | **FIXED in Task 7.4a** (a link to a missing or rejected item becomes None and is listed in the message). Was: If a spec_item that is a `previous`/`p_link`/`s_link` target fails to import, the link-resolution step raises an uncaught `KeyError` (HTTP 500) and the project is left half imported. Non-referenced failures are reported with the "Probable causes" message and skipped. No success message is ever issued for `import_project`. |
| export-eval-ref-not-converted | editor/utilities.py:106-117 | `spec_item_to_export` converts `ref_text` only; `eval_ref` fields (DataItem/EnumValue `Value`) are exported as raw `#iref:N` while `export_project` converts them. A CSV exported from one project is then not portable to another. | (open, awaiting operator approval: docs/fixes/tickets/export-eval-ref-raw.md)
| export-dangling-ref-literal | editor/convert.py:236 | A dangling `#iref:N` is exported as `ERROR:N` and re-imports as that literal text. | (open, awaiting operator approval: docs/fixes/tickets/export-dangling-ref-literal.md)
| import-link-ambiguous | editor/convert.py:211-220 | **FIXED in Task 7.4b** (unknown or ambiguous link targets are listed as warnings (row imported without the link)). Was: `convert_exp_to_db` finds link targets by `domain:name` only (any category/ValSet); an ambiguous or unknown target silently becomes `None`. |
| import-spec-items-no-rollback | editor/views.py:920-1050 | **FIXED in Task 7.4b** (per-row import kept, each row saved atomically, an exception rejects only that row; one summary "N imported, M rejected" with line numbers and reasons (first 20)). Was: Rows are saved one by one; invalid rows are only counted, valid rows stay committed. |
| import-spec-items-abort-no-summary | editor/views.py:1048-1049 | **FIXED in Task 7.4b** (per-row import kept, each row saved atomically, an exception rejects only that row; one summary "N imported, M rejected" with line numbers and reasons (first 20)). Was: An exception inside the row loop aborts the import with a traceback message at line `i+2`; earlier rows stay saved and neither success nor error summary is shown. |
| import-spec-items-undefined-i | editor/views.py:1048-1049 | **FIXED in Task 7.3** (a non-UTF-8 upload gives the message "Uploaded file <name> is not UTF-8 encoded; nothing was imported" and a redirect). Was: A decode error (non UTF-8 upload) occurs before `i` exists, so the handler raises `UnboundLocalError` (HTTP 500). |
| import-spec-items-no-login-required | editor/views.py:920 | **FIXED in Task 7.2a** (`@login_required` added). Was: The view has no `@login_required` (anonymous requests are only refused through the project access check). |
| import-project-owner-not-member | editor/imports.py (project ZIP import) | **FIXED in Task 7.4a** (an owner who is not a project user stays the owner and becomes a read-only member if the account exists on this server, otherwise the item is assigned to the project owner; both are listed). Was: an item whose owner is neither project owner nor project user was dropped with KeyError, "probable cause (b)". |
| csv-export-not-reimportable | editor/views.py (import_spec_items) | **FIXED in Task 7.4b** (empty required text/choice fields are imported and listed as warnings; analysis in docs/fixes/csv-empty-required-fields.md). Was: spec-item CSV exports of production data contain rows that the importer rejected (identifier rule / empty required field): 448 of 11,046 rows. |

Notes (not bugs): the "too big" check uses `UploadedFile.DEFAULT_CHUNK_SIZE` (64 KiB), not
`FILE_UPLOAD_MAX_MEMORY_SIZE`; a UTF-8 BOM breaks the first header; `str(ValidationError)` is
shown with its list brackets in the identifier error message.

## FW Profile database (editor/ext_cats.py)

| id | location | current behaviour |
|----|----------|-------------------|
| ext-cats-sql-injection | editor/ext_cats.py:59,101,137,145,178,186,239,278 | **FIXED in Task 7.1 and 7.2c** (model paths fixed by upstream #91 (Task 7.1), FCP paths in Task 7.2c: queries parameterized, connection closed on every path, unknown id gives None with a warning). Was: All SQL is built by string concatenation (user e-mail and ids are not escaped or parameterised). |
| ext-fcp-refresh-nameerror | editor/ext_cats.py:294-295 | **FIXED in Task 7.2c** (the FCP refresh sets title/description on the spec item). Was: `ext_fcp_refresh` writes to the undefined `ext_item_dict` (copy/paste), so any real refresh raises `NameError` after domain/name were already overwritten. |
| ext-cats-get-choice-not-found | editor/ext_cats.py:106,244 | **FIXED in Task 7.1 and 7.2c** (model paths fixed by upstream #91 (Task 7.1), FCP paths in Task 7.2c: queries parameterized, connection closed on every path, unknown id gives None with a warning). Was: `ext_model_get_choice`/`ext_fcp_get_choice` raise `IndexError` for an unknown id although documented to return `None`. |
| ext-cats-fcp-no-title | editor/ext_cats.py:251 | **FIXED in Task 7.2c** (an FCP without a `Title:` note yields empty title/description plus a warning). Was: An FCP without a `Title:` note makes `get_fcp_desc` return `None` and `ext_fcp_get_choice` fail with `TypeError`. |
| ext-cats-null-domain | editor/ext_cats.py:168-170,208-212 | **FIXED in Task 7.2c** (a model without domain is listed with an empty domain (FCP list: skipped)). Was: A model whose `smTags` is null makes the choice builders raise `TypeError` (`None + str`). |
| ext-cats-connection-leak | editor/ext_cats.py (early returns) | **FIXED in Task 7.1 and 7.2c** (model paths fixed by upstream #91 (Task 7.1), FCP paths in Task 7.2c: queries parameterized, connection closed on every path, unknown id gives None with a warning). Was: `fw_db.close()` is only called on success paths; error and `NO_CHANGE` returns leave the connection open. When `connect()` fails, the `(None, None)` result cascades into misleading "not found"/"Error while accessing" messages. |

## Authentication

| id | location | current behaviour |
|----|----------|-------------------|
| honeypot-logger-not-connected | editor/signals/handlers.py:1-11, editor/apps.py | **FIXED in Task 7.2a** (`EditorConfig.ready()` imports the existing receiver). Was: The `honeypot` receiver is never imported (`EditorConfig` has no `ready()`), so no `admin.honeypot` log record is written; the signal has no receivers (`ADMIN_HONEYPOT_EMAIL_ADMINS = False`). Attempts are only stored in `LoginAttempt`. |
| login-url-default | cordetfw_editor/settings.py (LOGIN_URL unset) | **FIXED in Task 7.2a** (`LOGIN_URL` is `/editor/login/`). Was: `@login_required` redirects to `/accounts/login/`, which is not routed (404); the real login is `/editor/login/`. |
| logout-unsafe-next-self-redirect | django `LogoutView` via `editor/urls.py` (`django.contrib.auth.urls`) | **FIXED in Task 3.4** (accepted upstream change, Django 4.2 (040e103)). Was: `GET /editor/logout/?next=//evil.example/` (unsafe next) logs the user out and redirects to `/editor/logout/` itself instead of `LOGOUT_REDIRECT_URL` (`/editor`): a redirect loop in the browser. Stock Django 3.2 behaviour; safe `next` and no `next` work. |

Behaviour to remember during the upgrade (pinned, expected to change):
`GET /editor/logout/` logs out (`# EXPECTED-CHANGE: Django 5 requires POST logout`); the lockout
response is HTTP 429 rendering `editor/templates/lockout.html` (resolved through the
`../templates/lockout.html` path); axes locks by IP after 3 failures with a 3 minute cooloff.

## Export filenames and JSON (added with the second test pass)

| id | location | current behaviour |
|----|----------|-------------------|
| export-filename-not-escaped | editor/views.py:914 (export_spec_items) | `Content-Disposition` is built by hand (`attachment; filename= "<name>"`, note the space after `=`) on a plain `HttpResponse`; double quotes in project/application names are not escaped, latin-1 characters are sent raw, and other non-ASCII names become an RFC 2047 `=?utf-8?b?...?=` encoded word that browsers do not decode for this header. (`export_project` uses `FileResponse`, whose escaping Django itself changes in 3.2.15+/4.2+; marked EXPECTED-CHANGE.) | (open, awaiting operator approval: docs/fixes/tickets/export-filename-not-escaped.md)
| export-s-data-key-order | editor/resources.py (SpecItemResource, `s_data` column) | **WONTFIX** (operator 2026-10-24: closed; JSON key order is a property of the database, changing it would change export bytes). The `s_data` JSON text in `spec_items.csv` follows the storage order of the database: insertion order on SQLite, MySQL's normalised order (shorter keys first, then bytewise) on MySQL. Not exported by `export_spec_items`. |
