# Known issues: editor/views.py (pinned by tests/test_views.py and the golden pages)

These behaviours are pinned as-is by the characterization suite and must be fixed
only after the Django upgrade, in separate changes.

| id | where | current behaviour |
|----|-------|-------------------|
| `index-username-substring` | editor/views.py:104 | `user__username__contains=<request user>` makes `user_has_access` true for user `bob` on a project assigned to `bobby` (substring match, also for `AnonymousUser`). Affects export and "manage item" links on the index page. |
| `change-password-no-response` | editor/views.py:139-151 | `change_password` returns `None` for GET and for an invalid POST (no `render`), so Django raises `ValueError` (HTTP 500). Only a valid POST works (redirect to itself). |
| `edit-project-del-user-unscoped` | editor/views.py:240 | `?del_user_id=` deletes `ProjectUser` by its id without checking it belongs to the project in the URL; any staff user can delete a membership of another project via any project URL. |
| `find-replace-no-write-check` | editor/views.py (list_spec_items, POST branch, 506-540) | The find and replace POST in `list_spec_items` only requires read access; a read-only (`RO`) project user can modify items (title, name, ...), and becomes their owner. |
| `add-p-parent-label-keyerror` | editor/views.py:617 | `add_spec_item?p_parent_id=` builds the sub title from `attrs['s_link']['label']`, (copy/paste of the s_parent branch). For categories without an `s_link` attribute (e.g. DataItem under an EnumType p_parent) this raises `KeyError` (HTTP 500); for others the sub title uses the s_link label, not the p_link label. |
| `copy-unreachable-valset-message` | editor/views.py:739-743 | `copy_spec_item` on an item outside the Default ValSet redirects to the index silently (first `or` condition); the error message in the second check ("Only SpecItems in default ValSet can be copied") is unreachable. |
| `list-500s` | editor/views.py:434, 468, 477, 543, and utilities.py:194, 488 | Unvalidated GET parameters in `list_spec_items` give HTTP 500s instead of 4xx: unknown `disp` or `cat` (`KeyError`), non-integer `page` (`ValueError`), out-of-range `page` (`EmptyPage`), unknown `order_by` (`FieldError`), `expand_id` without `expand_link` (`KeyError: None`). |
| `ref-link-backslash` | editor/convert.py:75, editor/templatetags/ref_filters.py:99,107 | Internal reference hyperlinks in descriptions end in `0\list_spec_items` (backslash instead of `/`, from an unescaped `'\l'` string). Visible in `tests/golden/pages/list_data_items.html`. |
| `refresh-timestamp-overwritten` | editor/views.py (refresh_spec_item) | After a REFRESH the item's `updated_at` set from the external DB by `ext_model_refresh` is immediately overwritten by `datetime.now()`. Pinned by `test_refresh_changed`. |
| `ext-fcp-refresh-undefined-name` | editor/ext_cats.py (`ext_fcp_refresh`) | References undefined `ext_item_dict` (NameError); not reachable from tests of this file (only `ext_model_refresh` is exercised). Noted only. |
| `mutation-via-get` | editor/views.py (del_project, del_spec_item for NEW items, edit_project with `user_id` / `del_*`) | State-changing operations on GET requests (no CSRF protection). |
| `login-echoes-password` | templates/registration/login.html (password input) | The password input renders `value="{{ form.password.value }}"`: after a failed login POST the typed password is echoed back in the HTML (`value="..."`). Pinned by `tests/golden/pages/login_failed_post.html`. |
| `form-none-literal` | templates/registration/login.html, editor/templates/make_release.html, editor/templates/generic_form_field.html (number/textarea inputs) | Unbound forms render the literal string `None` as input value / textarea content (login username/password `value="None"`, make-release description textarea `None`). Pinned by `login.html`, `make_project_release.html` and `test_snapshot_login_get_has_none_values`. |
| `p-link-selection-lost` | editor/templates/generic_form_field.html:95 | `{% if field.value == choice.0 %}` compares the posted string (e.g. `"1"`) with an int choice id, so after an invalid edit/add POST the `p_link` (and other select) selection is lost on re-render (no `selected`). Pinned by `tests/golden/pages/edit_spec_item_invalid_post.html`. |

## add-spec-item-val-set-post (not pinned by a test)
`add_spec_item` POST that includes a `val_set` field raises
`AttributeError: 'NoneType' object has no attribute 'model'` (500): in add mode the
`val_set` field has no queryset (`editor/forms.py`, SpecItemForm add mode). The real
form never posts the field (it is hidden), so this is only reachable by crafted requests.
