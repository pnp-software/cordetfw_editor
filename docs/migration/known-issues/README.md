# Known pre-existing issues

Found while building the characterization suite (2026-10-23). Each issue is pinned
**as-is** by a test marked `# KNOWN-ISSUE: <id>` and is **not** fixed in the
migration. Fix them afterwards in separate, reviewed changes, updating the
corresponding test in the same commit.

| File | Area |
| --- | --- |
| [models-access-releases-query.md](models-access-releases-query.md) | Models, permissions, releases, query visibility |
| [forms-convert-utilities.md](forms-convert-utilities.md) | Forms, reference conversion, markdown, template filters, utilities |
| [views.md](views.md) | Views |
| [import-export-auth.md](import-export-auth.md) | Project/CSV import-export, FW Profile DB, auth |
| [security-audit.md](security-audit.md) | Security audit (Task 6.2): cross-project access, DoS, injection, operator checks |

## Highest priority (recommend fixing soon, independent of the migration)

1. **`add-app-releases-null-app-items`** (`views.py:166` → `utilities.py:257`):
   adding an application calls `do_application_release` before the application is
   saved, so it filters `application_id=None` and sets **every NEW/MOD project-level
   item in every project to CNF**. Silent data change in production.
2. **`idor-item-project`** (`views.py:646`, `:819`): item ids are not checked against
   the project in the URL; write access to project A allows editing or deleting
   NEW items of project B.
3. **XSS**: `xss-display`, `xss-tag`, `md-no-escape`: user text is `mark_safe`d unescaped.
4. **SQL injection** in `editor/ext_cats.py` (string-built SQL against the FW Profile DB).
5. **`find-replace-no-write-check`**, **`import-no-login-required`**,
   **`edit-project-del-user-unscoped`**, **`mutation-via-get`**: missing or wrong
   authorization and state changes on GET.
6. **Data loss in project import**: ProjectUser `role`, SpecItem `created_at`,
   `application_version` and `s_data` are not restored faithfully; import is not atomic.
7. **Emoji**: MySQL connections use Django's default 3-byte `utf8` charset, so 4-byte
   characters raise an error on save (pinned in `tests/test_db_backend.py`).
