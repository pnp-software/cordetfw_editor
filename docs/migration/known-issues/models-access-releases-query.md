# Known issues: models, access, releases, query

Pinned by `tests/test_models.py`, `tests/test_access.py`, `tests/test_releases.py`,
`tests/test_query.py`. Observed on the baseline (Python 3.12, Django 3.2.0). Not to be fixed
before the migration is complete; each fix goes in its own change.

| id | where | observed behaviour | test |
|----|-------|--------------------|------|
| naive-created-at-default | editor/models.py:65 | `SpecItem.created_at` default is the naive `datetime(2000, 1, 1)`. With `USE_TZ=True` Django emits a RuntimeWarning on save and stores it as 2000-01-01 00:00 UTC; the unsaved instance keeps the naive value, a reloaded one is aware. | test_models.py::test_spec_item_created_at_default_naive_datetime_stored_as_utc |
| release-version-default-str | editor/models.py:11-12 | `Release.project_version` / `application_version` use `default="0"` (a string). An unsaved instance holds `'0'`; after save and reload it is the int `0`. | test_models.py::test_release_version_defaults |
| access-first-row | editor/access.py:30-31 | `has_write_access_to_project` uses `ProjectUser.objects.filter(...)[0].role` (unordered). A user with duplicate ProjectUser rows is judged by whichever row comes first. A bare `except Exception` also turns any error into the "read/write access" denial. | test_access.py::test_write_access_uses_first_project_user_row |
| import-no-login-required | editor/views.py:920 | `import_spec_items` has no `@login_required`. Anonymous requests are not sent to `/accounts/login/`; they fail the write-access check and get a 302 to `/editor` with "This operation requires read/write access to project <name>". Nothing is imported. | test_access.py::test_import_spec_items_has_no_login_required, test_import_spec_items_anonymous_post_does_not_import |
| idor-item-project | editor/views.py:646, 819 (also copy/split/refresh) | The `item_id` in the URL is never checked against `project_id`. A user with write access to project A can open the edit form of an item of project B, or delete a NEW item of project B, by putting A's project id in the URL. Deleting a NEW item happens on a plain GET. | test_access.py::test_item_of_project_b_editable_through_project_a_url |
| add-app-releases-null-app-items | editor/views.py:166 with editor/utilities.py:257 | `add_application` calls `do_application_release` on the unsaved Application (id None). `filter(application_id=None)` matches every spec item with no application, in ALL projects, and turns NEW/MOD ones into CNF. | test_releases.py::test_add_application_releases_all_items_without_application, test_do_application_release_for_new_application_without_release |
| app-cats-substring | editor/forms.py:88 | `ApplicationForm.clean_cats` checks `cat in project.cats` on the raw string, so a substring such as `Data` (from `DataItem`) is accepted as an application category. | test_releases.py::test_add_application_category_check_is_a_substring_match |
| make-temp-dir-name-error | editor/utilities.py:313-318 | If the export directory already exists (two exports within the same second), the `except OSError` handler references the undefined names `request` and `exp_dir`, so a `NameError` escapes (HTTP 500 from `export_project`) instead of the intended message and `''`. | test_query.py::test_make_temp_dir_failure_path_raises_name_error |

## Other behaviour pinned (not bugs, but worth knowing)

- `edit_project`, `del_project` and `add_val_set` are gated by `is_staff` only. The project owner
  needs staff rights to use them. Staff and superusers get no project read/write access
  unless they are owner or ProjectUser.
- `make_obs_spec_item_copy` mutates its argument into the OBS copy (new pk) and returns the original
  row as an unsaved MOD instance. The docstring suggests the reverse.
- Releases do not filter by ValSet, and item `updated_at` is not changed by a release.
- `do_project_release` releases every application of the project, resetting its application_version to 0.
