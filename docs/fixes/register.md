# Fix register

One row per known issue (canonical id; aliases are the ids used in older docs/tests).
Track: S = urgent security, on `upgrade/django-lts`; K = `fix/known-issues`; W = won't fix / later.
Status: OPEN, FIXED in <commit>, WONTFIX. Checked by `scripts/known_issue_check.py`.

| id | aliases | doc | tests | track | status | decision |
| --- | --- | --- | --- | --- | --- | --- |
| access-first-row | — | models-access-releases-query.md | tests/test_access.py | K | OPEN | Operator 2026-10-24: any RW row wins |
| add-app-releases-null-app-items | — | models-access-releases-query.md | tests/test_releases.py | S | FIXED (Task 6.5) | Data impact in production: docs/fixes/add-app-release-data-impact.md (report only) |
| add-p-parent-label-keyerror | — | views.md | tests/test_views.py | K | OPEN |  |
| add-spec-item-val-set-post | — | views.md | — | K | OPEN |  |
| appform-cats-substring | app-cats-substring | forms-convert-utilities.md, models-access-releases-query.md | tests/test_forms.py, tests/test_releases.py | K | OPEN |  |
| axes-ip-only-lockout | — | security-audit.md | tests/test_security_audit.py | S | OPEN | No proxy, so REMOTE_ADDR is the client IP: shared-lockout DoS not applicable; distributed brute force remains. optional AXES_LOCKOUT_PARAMETERS key added in Task 6.7; default unchanged (operator choice) |
| change-password-no-response | — | views.md | tests/test_views.py | K | OPEN |  |
| conv-date-nameerror | — | forms-convert-utilities.md | tests/test_convert.py | K | OPEN |  |
| copy-unreachable-valset-message | — | views.md | tests/test_views.py | K | OPEN |  |
| csv-export-not-reimportable | — | import-export-auth.md | — | K | OPEN | Spec-item CSV exports of production data contain rows that the importer's row checks reject (identifier rule / empty required field): 448 of 11,046 rows, 436 in one project; 447 empty required field (Requirement 399), 1 identifier rule. Found in Task 6.8e; identical with the production code (Task 6.8f) |
| csv-formula-injection | — | security-audit.md | tests/test_security_audit.py | K | OPEN | Export byte change, awaiting operator approval: docs/fixes/tickets/csv-formula-injection.md |
| dataitem-no-plink | — | forms-convert-utilities.md | tests/test_forms.py | K | OPEN |  |
| disp-trac-plink-none | — | forms-convert-utilities.md | tests/test_convert.py | K | OPEN |  |
| edit-project-del-user-unscoped | — | views.md | tests/test_views.py | S | FIXED in 1b2bb5a | the merged upstream #86 branch scopes the delete to the URL's project (Task 6.3) |
| edit-project-valset-unscoped | — | security-audit.md | tests/test_security_audit.py | S | FIXED (Task 6.4) |  |
| enum-value-no-type | — | forms-convert-utilities.md | tests/test_forms.py | K | OPEN |  |
| eval-ref-dos | — | security-audit.md | tests/test_security_audit.py | K | OPEN |  |
| exp-ref-no-dots | — | forms-convert-utilities.md | tests/test_convert.py | K | OPEN |  |
| export-dangling-ref-literal | — | import-export-auth.md | tests/test_import_export.py | K | OPEN | Export byte change, awaiting operator approval: docs/fixes/tickets/export-dangling-ref-literal.md |
| export-eval-ref-raw | export-eval-ref-not-converted | forms-convert-utilities.md, import-export-auth.md | tests/test_import_export.py, tests/test_utilities.py | K | OPEN | Export byte change, awaiting operator approval: docs/fixes/tickets/export-eval-ref-raw.md |
| export-filename-not-escaped | — | import-export-auth.md | tests/test_import_export.py | K | OPEN | Export byte change, awaiting operator approval: docs/fixes/tickets/export-filename-not-escaped.md |
| export-none-string | — | forms-convert-utilities.md | tests/test_utilities.py | K | OPEN | Export byte change, awaiting operator approval: docs/fixes/tickets/export-none-string.md |
| export-s-data-key-order | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| ext-cats-connection-leak | — | import-export-auth.md | tests/test_ext_cats.py | K | OPEN | Model paths fixed by upstream #91 (Task 7.1); FCP paths open |
| ext-cats-fcp-no-title | — | import-export-auth.md | tests/test_ext_cats.py | K | OPEN |  |
| ext-cats-get-choice-not-found | — | import-export-auth.md | tests/test_ext_cats.py | K | OPEN | Model paths fixed by upstream #91 (Task 7.1); FCP paths open |
| ext-cats-null-domain | — | import-export-auth.md | tests/test_ext_cats.py | K | OPEN |  |
| ext-cats-sql-injection | — | import-export-auth.md, security-audit.md | tests/test_ext_cats.py | K | OPEN | Model paths fixed by upstream #91 (Task 7.1); FCP paths open |
| ext-fcp-refresh-nameerror | ext-fcp-refresh-undefined-name | import-export-auth.md, views.md | tests/test_ext_cats.py | K | OPEN |  |
| find-replace-no-write-check | — | views.md | tests/test_views.py | S | FIXED (Task 6.4) |  |
| find-replace-on-release-view | — | views.md | — | K | OPEN | Find & Replace is offered on release views (sel_rel_id != 0) whose query includes CNF/OBS/DEL historical rows, so it could rewrite OBS versions. Found by the Task 6.4 review |
| form-none-literal | — | views.md | tests/test_rendering_snapshots.py | K | OPEN |  |
| help-double-space | — | forms-convert-utilities.md | tests/test_forms.py | K | OPEN |  |
| honeypot-logger-not-connected | — | import-export-auth.md | tests/test_auth.py | K | OPEN |  |
| idor-app-valset-cross-project | — | security-audit.md | tests/test_security_audit.py | S | FIXED (Task 6.4) |  |
| idor-app-write-cross-project | — | security-audit.md | tests/test_security_audit.py | S | FIXED (Task 6.4) |  |
| idor-item-project | — | models-access-releases-query.md, security-audit.md | tests/test_access.py, tests/test_security_audit.py | S | FIXED (Task 6.4) |  |
| idor-parent-link-cross-project | — | security-audit.md | tests/test_security_audit.py | S | FIXED (Task 6.4) |  |
| image-svg-unsanitised | — | security-audit.md | tests/test_escaping_6_6.py | S | FIXED (Task 6.6c) | Kind `image` (Model/FCP SVG from FW Profile) rendered raw; exempt from Task 6.6 escaping (operator 2026-10-23). Write paths closed/deny-list in Task 6.6b (editor/svg_check.py; edit/copy/split ignore posted FW Profile attributes; Find & Replace refuses them); Task 6.6c: strict allowlist validator (validate only) on every write path + render placeholder for stored values that fail |
| import-link-ambiguous | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| import-no-login-required | import-spec-items-no-login-required | import-export-auth.md, models-access-releases-query.md | tests/test_access.py | K | OPEN |  |
| import-project-application-version-lost | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| import-project-attribution-forgery | — | security-audit.md | tests/test_security_audit.py | K | OPEN |  |
| import-project-auto-now-timestamps | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| import-project-created-at-lost | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| import-project-crlf-lost | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| import-project-dangling-link-crash | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| import-project-empty-app-cats | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| import-project-no-limits | — | security-audit.md | tests/test_security_audit.py | K | OPEN |  |
| import-project-not-atomic | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| import-project-owner-not-member | — | import-export-auth.md | — | K | OPEN | Project ZIP import drops items whose owner is neither project owner nor project user (KeyError, "probable cause (b)"). Production (dump 2026-10-21): 35 items in 1 project would be lost on export -> import. Found in Task 6.8e; identical with the production code (Task 6.8f) |
| import-project-role-lost | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| import-project-s-data-double-encoded | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| import-spec-items-abort-no-summary | — | import-export-auth.md | tests/test_import_export.py | K | OPEN | Operator 2026-10-24: keep per-row import, always show a summary |
| import-spec-items-no-rollback | — | import-export-auth.md | tests/test_import_export.py | K | OPEN | Operator 2026-10-24: keep per-row import, always show a summary |
| import-spec-items-undefined-i | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| import-traceback-in-message | — | security-audit.md | tests/test_security_audit.py | K | OPEN |  |
| index-lists-all-projects | — | security-audit.md | tests/test_security_audit.py | K | OPEN | Operator 2026-10-24: non-staff see only own/member projects; staff see all |
| index-username-substring | — | views.md | tests/test_views.py | K | OPEN |  |
| iref-cross-project-disclosure | — | security-audit.md | tests/test_security_audit.py | K | OPEN |  |
| latex-export-injection | — | security-audit.md | tests/test_security_audit.py | K | OPEN | Export byte change, awaiting operator approval: docs/fixes/tickets/latex-export-injection.md |
| link-suggest-js-string | — | security-audit.md | tests/test_security_audit.py | S | FIXED (Task 6.6b) | Stored XSS (`\x3c` in a title decoded to `<` before the jQuery html: sink); template filter js_str_after_html_escape |
| list-500s | — | views.md | tests/test_views.py | K | OPEN |  |
| login-echoes-password | — | views.md | tests/test_rendering_snapshots.py | K | OPEN |  |
| login-url-default | — | import-export-auth.md | tests/test_auth.py | K | OPEN |  |
| logout-unsafe-next-self-redirect | — | import-export-auth.md | tests/test_auth.py | — | FIXED in 040e103 (upstream Django 4.2, Task 3.4) | Accepted upstream change; test marker is the old free-text form |
| make-temp-dir-nameerror | make-temp-dir-name-error, temp-dir-collision | forms-convert-utilities.md, import-export-auth.md, models-access-releases-query.md | tests/test_import_export.py, tests/test_query.py, tests/test_utilities.py | K | OPEN |  |
| md-no-escape | — | forms-convert-utilities.md | tests/test_convert.py | S | OPEN | HTML part fixed in Task 6.6 (convert_db_to_display escapes before markdown_to_html; tests/test_escaping_6_6.py). Still open for track K: LaTeX escaping in markdown_to_latex (export bytes must stay identical until then) and markdown nesting/first-list-item |
| mutation-via-get | — | views.md, security-audit.md | tests/test_views.py, tests/test_security_audit.py, tests/test_access.py, tests/test_post_only_mutations.py | S | FIXED (Task 6.3) | merge of upstream #86 + POST-only refresh/member add/role validation |
| naive-created-at-default | — | models-access-releases-query.md | tests/test_models.py | K | OPEN |  |
| no-secure-proxy-ssl-header | — | security-audit.md | tests/test_security_audit.py | — | WONTFIX | Not applicable: TLS ends at Apache (mod_ssl + mod_wsgi in the same vhost, no proxy); operator 2026-10-23 |
| order-by-unrestricted | — | security-audit.md | tests/test_security_audit.py | K | OPEN |  |
| outcomponent-disp-short-keyerror | — | views.md | — | K | OPEN | configs.json OutComponent `disp_short` lists `value`, not in its attrs: conv_db_disp KeyError (500). Found by the Task 6.6 scan |
| owner-empty-names | — | forms-convert-utilities.md | tests/test_utilities.py | K | OPEN |  |
| p-link-selection-lost | — | views.md | tests/test_rendering_snapshots.py | K | OPEN |  |
| redirect-int-parent | — | forms-convert-utilities.md | tests/test_utilities.py | K | OPEN |  |
| ref-link-backslash | — | forms-convert-utilities.md, views.md | tests/test_convert.py, tests/test_rendering_snapshots.py | K | OPEN |  |
| refresh-not-shared-double-message | — | views.md | — | K | OPEN | Refresh of a model that exists but is not shared with the user shows "Model not found or not shared with you..." followed by "External spec_item no longer exists -- no refresh can be done". Found by the Task 7.1 review |
| refresh-timestamp-overwritten | — | views.md | tests/test_views.py | K | OPEN |  |
| release-id-unscoped | — | security-audit.md | tests/test_security_audit.py | S | FIXED (Task 6.4) |  |
| release-version-default-str | — | models-access-releases-query.md | tests/test_models.py | K | OPEN |  |
| s-data-string | — | forms-convert-utilities.md | tests/test_forms.py | K | OPEN |  |
| session-and-reset-hardening | — | security-audit.md | tests/test_security_audit.py | K | OPEN | HSTS + port 80 redirect done by Apache (operator 2026-10-23); session length/CSP defaults remain, low |
| temp-dir-not-cleaned | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| temp-files-world-readable | — | security-audit.md | tests/test_security_audit.py | K | OPEN |  |
| tracked-dev-secret-key | — | security-audit.md | tests/test_security_audit.py | K | OPEN | Production uses a different SECURE_KEY (operator 2026-10-23): not exploitable. Cleanup: replace tracked file by an .example |
| xss-display | — | forms-convert-utilities.md | tests/test_convert.py, tests/test_escaping_6_6.py | S | FIXED (Task 6.6) | Text nodes escape only & < > (escape_text), attributes full escape(); kind `image` exempt |
| xss-tag | — | forms-convert-utilities.md | tests/test_convert.py, tests/test_escaping_6_6.py | S | FIXED (Task 6.6) | conv_db_disp, filter_expand_tip (attribute), disp_trac; kind `image` exempt |

## Marker ids not in any doc

none

## Doc ids without a test marker

- add-spec-item-val-set-post
