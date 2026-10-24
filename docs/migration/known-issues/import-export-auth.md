# Known issues: import/export, FW Profile access, authentication

Pinned by `tests/test_import_export.py`, `tests/test_ext_cats.py`, `tests/test_auth.py`
(grep for `KNOWN-ISSUE: <id>`). None is fixed during the migration.

## Import / export

| id | location | current behaviour |
|----|----------|-------------------|
| temp-dir-collision | editor/utilities.py:309-319 | `make_temp_dir` names the directory by timestamp (1 s). A second export/import within the same second hits `OSError`; the handler uses undefined `request` and `exp_dir`, so a `NameError` (HTTP 500) results. |
| temp-dir-not-cleaned | editor/views.py:1097-1150, editor/views.py:1057-1090 | Export and import directories (CSV files, zip) are never removed from `temp_dir`. |
| import-project-role-lost | editor/imports.py:169-173 | `ProjectUser.role` is not read from `project_users.csv`; every user is imported as `RO`. |
| import-project-created-at-lost | editor/imports.py:192-221 | `SpecItem.created_at` is not imported; it takes the model default `2000-01-01`. |
| import-project-application-version-lost | editor/imports.py:136-140 | `Release.application_version` is not imported (always 0). |
| import-project-s-data-double-encoded | editor/imports.py:206 | `s_data` JSON text from the CSV is assigned as a string, so the JSONField stores a JSON string (and `{}` becomes `""`); a re-export yields `"{\"a\": 1}"`. |
| import-project-auto-now-timestamps | editor/imports.py:149-185 | `updated_at` of Project, Application, ValSet and ProjectUser are `auto_now` fields; the values in the CSV are overwritten by the import time. |
| import-project-crlf-lost | editor/imports.py:20-21,49-51 | Files are opened with `open(..., 'r')` (universal newlines): a CR LF inside a field comes back as LF. |
| import-project-empty-app-cats | editor/imports.py:100-105 | An application with empty `cats` cannot be imported (`''.split(',') == ['']`, not a configured category); message is `The category  in application X is not defined in configs.json`. |
| import-project-not-atomic | editor/imports.py:130-146 | Import is not transactional: a failure after some writes (e.g. unknown release author) leaves the already created Release rows behind. |
| import-project-dangling-link-crash | editor/imports.py:228-241 | If a spec_item that is a `previous`/`p_link`/`s_link` target fails to import, the link-resolution step raises an uncaught `KeyError` (HTTP 500) and the project is left half imported. Non-referenced failures are reported with the "Probable causes" message and skipped. No success message is ever issued for `import_project`. |
| export-eval-ref-not-converted | editor/utilities.py:106-117 | `spec_item_to_export` converts `ref_text` only; `eval_ref` fields (DataItem/EnumValue `Value`) are exported as raw `#iref:N` while `export_project` converts them. A CSV exported from one project is then not portable to another. |
| export-dangling-ref-literal | editor/convert.py:236 | A dangling `#iref:N` is exported as `ERROR:N` and re-imports as that literal text. |
| import-link-ambiguous | editor/convert.py:211-220 | `convert_exp_to_db` finds link targets by `domain:name` only (any category/ValSet); an ambiguous or unknown target silently becomes `None`. |
| import-spec-items-no-rollback | editor/views.py:920-1050 | Rows are saved one by one; invalid rows are only counted, valid rows stay committed. |
| import-spec-items-abort-no-summary | editor/views.py:1048-1049 | An exception inside the row loop aborts the import with a traceback message at line `i+2`; earlier rows stay saved and neither success nor error summary is shown. |
| import-spec-items-undefined-i | editor/views.py:1048-1049 | A decode error (non UTF-8 upload) occurs before `i` exists, so the handler raises `UnboundLocalError` (HTTP 500). |
| import-spec-items-no-login-required | editor/views.py:920 | The view has no `@login_required` (anonymous requests are only refused through the project access check). |

Notes (not bugs): the "too big" check uses `UploadedFile.DEFAULT_CHUNK_SIZE` (64 KiB), not
`FILE_UPLOAD_MAX_MEMORY_SIZE`; a UTF-8 BOM breaks the first header; `str(ValidationError)` is
shown with its list brackets in the identifier error message.

## FW Profile database (editor/ext_cats.py)

| id | location | current behaviour |
|----|----------|-------------------|
| ext-cats-sql-injection | editor/ext_cats.py:59,101,137,145,178,186,239,278 | All SQL is built by string concatenation (user e-mail and ids are not escaped or parameterised). |
| ext-fcp-refresh-nameerror | editor/ext_cats.py:294-295 | `ext_fcp_refresh` writes to the undefined `ext_item_dict` (copy/paste), so any real refresh raises `NameError` after domain/name were already overwritten. |
| ext-cats-get-choice-not-found | editor/ext_cats.py:106,244 | `ext_model_get_choice`/`ext_fcp_get_choice` raise `IndexError` for an unknown id although documented to return `None`. |
| ext-cats-fcp-no-title | editor/ext_cats.py:251 | An FCP without a `Title:` note makes `get_fcp_desc` return `None` and `ext_fcp_get_choice` fail with `TypeError`. |
| ext-cats-null-domain | editor/ext_cats.py:168-170,208-212 | A model whose `smTags` is null makes the choice builders raise `TypeError` (`None + str`). |
| ext-cats-connection-leak | editor/ext_cats.py (early returns) | `fw_db.close()` is only called on success paths; error and `NO_CHANGE` returns leave the connection open. When `connect()` fails, the `(None, None)` result cascades into misleading "not found"/"Error while accessing" messages. |

## Authentication

| id | location | current behaviour |
|----|----------|-------------------|
| honeypot-logger-not-connected | editor/signals/handlers.py:1-11, editor/apps.py | The `honeypot` receiver is never imported (`EditorConfig` has no `ready()`), so no `admin.honeypot` log record is written; the signal has no receivers (`ADMIN_HONEYPOT_EMAIL_ADMINS = False`). Attempts are only stored in `LoginAttempt`. |
| login-url-default | cordetfw_editor/settings.py (LOGIN_URL unset) | `@login_required` redirects to `/accounts/login/`, which is not routed (404); the real login is `/editor/login/`. |
| logout-unsafe-next-self-redirect | django `LogoutView` via `editor/urls.py` (`django.contrib.auth.urls`) | `GET /editor/logout/?next=//evil.example/` (unsafe next) logs the user out and redirects to `/editor/logout/` itself instead of `LOGOUT_REDIRECT_URL` (`/editor`): a redirect loop in the browser. Stock Django 3.2 behaviour; safe `next` and no `next` work. |

Behaviour to remember during the upgrade (pinned, expected to change):
`GET /editor/logout/` logs out (`# EXPECTED-CHANGE: Django 5 requires POST logout`); the lockout
response is HTTP 429 rendering `editor/templates/lockout.html` (resolved through the
`../templates/lockout.html` path); axes locks by IP after 3 failures with a 3 minute cooloff.

## Export filenames and JSON (added with the second test pass)

| id | location | current behaviour |
|----|----------|-------------------|
| export-filename-not-escaped | editor/views.py:914 (export_spec_items) | `Content-Disposition` is built by hand (`attachment; filename= "<name>"`, note the space after `=`) on a plain `HttpResponse`; double quotes in project/application names are not escaped, latin-1 characters are sent raw, and other non-ASCII names become an RFC 2047 `=?utf-8?b?...?=` encoded word that browsers do not decode for this header. (`export_project` uses `FileResponse`, whose escaping Django itself changes in 3.2.15+/4.2+; marked EXPECTED-CHANGE.) |
| export-s-data-key-order | editor/resources.py (SpecItemResource, `s_data` column) | The `s_data` JSON text in `spec_items.csv` follows the storage order of the database: insertion order on SQLite, MySQL's normalised order (shorter keys first, then bytewise) on MySQL. Not exported by `export_spec_items`. |
| import-project-owner-not-member | editor/imports.py (project ZIP import) | FIXED in Task 7.4a (was: an item whose owner is neither project owner nor project user was dropped with KeyError, "probable cause (b)"). |
