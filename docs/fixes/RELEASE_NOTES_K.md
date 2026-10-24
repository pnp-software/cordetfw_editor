# Release notes: known-issue fixes (track K)

Branch `fix/known-issues`, prepared 2026-10-24 on top of the Django 5.2 migration release (`track-s-rc1`,
branch `upgrade/django-lts`). Deploy **after** the migration release. Plan and status per issue:
`docs/fixes/register.md`; task log: `docs/migration/tasks.md` Phase 7.

## Deploy

- Run `manage.py migrate`: migrations `editor.0012` and `editor.0013` change model defaults only (no SQL on MySQL;
  the old code keeps working on the migrated database, so rollback = redeploy the previous release).
- Startup is refused when `DEBUG` is false and `SECURE_KEY` is the development placeholder or the key formerly
  tracked in git (production uses its own key: no action expected).
- New optional key in `/etc/dj_cordetfw_config.json`: `SESSION_COOKIE_AGE` (seconds, 300 to one year). Absent =
  unchanged (two weeks).
- Log parsers: the honeypot line for `/admin/` attempts is now actually written (logger `admin.honeypot`), with the
  username quoted.

## Visible changes

**Access and navigation**
- Index: non-staff users see only projects they own or are members of (one active production user is in no
  project and will see an empty list); staff see all; anonymous users see none.
- Write access is granted if any of the user's membership rows for the project is RW.
- Login page is `/editor/login/` for every protected page (including spec-item import); a failed login no longer
  shows the typed password again.
- List pages: unknown category → 404; an invalid display mode, page or expand parameter falls back to the default
  instead of an error page; sorting is limited to the offered columns (`-column` still works). Find & Replace is no
  longer offered on release views. Internal links use `/` instead of `\` (same targets).

**Spec-item CSV import**
- Every import ends with one summary: "N imported, M rejected", with line numbers and reasons, plus warnings.
- Each row is saved completely or not at all; an unexpected error rejects only that row.
- Rows with empty required fields are imported again, with a warning (why production has such rows:
  `docs/fixes/csv-empty-required-fields.md`). Empty or non-numeric number cells are rejected with a reason.
- Links whose names contain dots or dashes resolve; unknown or ambiguous links are imported empty with a warning.
- A file that is not UTF-8 gets a clear message. References to items of another project are removed (warning).

**Project ZIP import (staff)**
- All or nothing: a failure leaves no partial project.
- Restores member roles, application versions, creation and update times, CR LF line breaks, applications without
  categories, and `s_data` (limitation: a stored text that looks like a JSON object/list comes back as the object).
- Items whose owner is no longer a member are kept: an existing account becomes a read-only member, otherwise the
  item goes to the project owner; both are reported. Links to missing items are cleared and reported.
- Limits: 100 MB upload, 100 archive entries, 200 MB uncompressed; other entries are ignored.

**Values and references**
- Values with loops or assignments (`while`, `for`, `repeat`, `until`, `switch`, `var`, `:=`) are shown, not
  evaluated; reference expansion is capped. All 3,875 production values evaluate exactly as before.
- `#iref` references resolve only inside the item's own project (production has none across projects).

**FW Profile**
- Models shared with you (read or write share) can be listed, added and refreshed (upstream #91). Refreshing a model
  now needs ownership or a share: co-authors need an FW Profile share.
- One clear message when a model is not available. Refreshing a confirmed item keeps the previous diagram in its
  history copy (copies made by earlier refreshes are not corrected).

**Forms**
- A required choice stored empty (e.g. Requirement "Ver") shows an empty option that must be chosen, instead of
  silently saving the first choice (408 production items have such an empty field).
- No literal "None" in empty fields; the selected parent and owner are kept after a validation error; owner names
  without "( )"; the add-form subtitle uses the parent link label; Change Password works; deleting a split alias
  works (upstream #99); application categories must match the project categories exactly.
- Temporary export/import files are private (mode 0700) and removed after use.

## Unchanged (verified)

- Export bytes: rehearsal on the production dump of 2026-10-21, `track-s-rc1` vs this branch: 404/404 exports
  identical; 99 of 164 pages identical, 65 differ only by `\` → `/` in links; rollback to `track-s-rc1`:
  404/404 exports and 164/164 pages identical, sessions and passwords valid both ways.
- Exports of the current release import: compat corpus (17 inputs) plus re-import of all production exports
  (9 ZIPs, 107 CSVs): every item and 11,045 of 11,046 CSV rows import (before: 16,271 items, 10,598 rows).

Pages not covered by the rehearsal snapshot (check in staging): non-staff index, login, add/edit/copy/split forms
(blank choice option, no "None"), release views (no Find & Replace), Change Password.

## Pending (operator decision)

Export byte changes and `s-data-string` are not implemented; one ticket each in `docs/fixes/tickets/`.
