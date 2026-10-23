# Fix register

One row per known issue (canonical id; aliases are the ids used in older docs/tests).
Track: S = urgent security, on `upgrade/django-lts`; K = `fix/known-issues`; W = won't fix / later.
Status: OPEN, FIXED in <commit>, WONTFIX. Checked by `scripts/known_issue_check.py`.

| id | aliases | doc | tests | track | status | decision |
| --- | --- | --- | --- | --- | --- | --- |
| access-first-row | — | models-access-releases-query.md | tests/test_access.py | K | OPEN |  |
| add-app-releases-null-app-items | — | models-access-releases-query.md | tests/test_releases.py | S | OPEN |  |
| add-p-parent-label-keyerror | — | views.md | tests/test_views.py | K | OPEN |  |
| add-spec-item-val-set-post | — | views.md | — | K | OPEN |  |
| appform-cats-substring | app-cats-substring | forms-convert-utilities.md, models-access-releases-query.md | tests/test_forms.py, tests/test_releases.py | K | OPEN |  |
| axes-ip-only-lockout | — | security-audit.md | tests/test_security_audit.py | S | OPEN | optional config key / ROLLOUT operator check |
| change-password-no-response | — | views.md | tests/test_views.py | K | OPEN |  |
| conv-date-nameerror | — | forms-convert-utilities.md | tests/test_convert.py | K | OPEN |  |
| copy-unreachable-valset-message | — | views.md | tests/test_views.py | K | OPEN |  |
| csv-formula-injection | — | security-audit.md | tests/test_security_audit.py | K | OPEN |  |
| dataitem-no-plink | — | forms-convert-utilities.md | tests/test_forms.py | K | OPEN |  |
| disp-trac-plink-none | — | forms-convert-utilities.md | tests/test_convert.py | K | OPEN |  |
| edit-project-del-user-unscoped | — | views.md | tests/test_views.py | S | FIXED in 1b2bb5a | the merged upstream #86 branch scopes the delete to the URL's project (Task 6.3) |
| edit-project-valset-unscoped | — | security-audit.md | tests/test_security_audit.py | S | OPEN |  |
| enum-value-no-type | — | forms-convert-utilities.md | tests/test_forms.py | K | OPEN |  |
| eval-ref-dos | — | security-audit.md | tests/test_security_audit.py | K | OPEN |  |
| exp-ref-no-dots | — | forms-convert-utilities.md | tests/test_convert.py | K | OPEN |  |
| export-dangling-ref-literal | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| export-eval-ref-raw | export-eval-ref-not-converted | forms-convert-utilities.md, import-export-auth.md | tests/test_import_export.py, tests/test_utilities.py | K | OPEN |  |
| export-filename-not-escaped | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| export-none-string | — | forms-convert-utilities.md | tests/test_utilities.py | K | OPEN |  |
| export-s-data-key-order | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| ext-cats-connection-leak | — | import-export-auth.md | tests/test_ext_cats.py | K | OPEN |  |
| ext-cats-fcp-no-title | — | import-export-auth.md | tests/test_ext_cats.py | K | OPEN |  |
| ext-cats-get-choice-not-found | — | import-export-auth.md | tests/test_ext_cats.py | K | OPEN |  |
| ext-cats-null-domain | — | import-export-auth.md | tests/test_ext_cats.py | K | OPEN |  |
| ext-cats-sql-injection | — | import-export-auth.md, security-audit.md | tests/test_ext_cats.py, tests/test_security_audit.py | K | OPEN |  |
| ext-fcp-refresh-nameerror | ext-fcp-refresh-undefined-name | import-export-auth.md, views.md | tests/test_ext_cats.py | K | OPEN |  |
| find-replace-no-write-check | — | views.md | tests/test_views.py | S | OPEN |  |
| form-none-literal | — | views.md | tests/test_rendering_snapshots.py | K | OPEN |  |
| help-double-space | — | forms-convert-utilities.md | tests/test_forms.py | K | OPEN |  |
| honeypot-logger-not-connected | — | import-export-auth.md | tests/test_auth.py | K | OPEN |  |
| idor-app-valset-cross-project | — | security-audit.md | tests/test_security_audit.py | S | OPEN |  |
| idor-app-write-cross-project | — | security-audit.md | tests/test_security_audit.py | S | OPEN |  |
| idor-item-project | — | models-access-releases-query.md, security-audit.md | tests/test_access.py, tests/test_security_audit.py | S | OPEN |  |
| idor-parent-link-cross-project | — | security-audit.md | tests/test_security_audit.py | S | OPEN |  |
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
| import-project-role-lost | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| import-project-s-data-double-encoded | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| import-spec-items-abort-no-summary | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| import-spec-items-no-rollback | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| import-spec-items-undefined-i | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| import-traceback-in-message | — | security-audit.md | tests/test_security_audit.py | K | OPEN |  |
| index-lists-all-projects | — | security-audit.md | tests/test_security_audit.py | K | OPEN |  |
| index-username-substring | — | views.md | tests/test_views.py | K | OPEN |  |
| iref-cross-project-disclosure | — | security-audit.md | tests/test_security_audit.py | K | OPEN |  |
| latex-export-injection | — | security-audit.md | tests/test_security_audit.py | K | OPEN |  |
| link-suggest-js-string | — | security-audit.md | tests/test_security_audit.py | K | OPEN |  |
| list-500s | — | views.md | tests/test_views.py | K | OPEN |  |
| login-echoes-password | — | views.md | tests/test_rendering_snapshots.py | K | OPEN |  |
| login-url-default | — | import-export-auth.md | tests/test_auth.py | K | OPEN |  |
| logout-unsafe-next-self-redirect | — | import-export-auth.md | tests/test_auth.py | — | FIXED in 040e103 (upstream Django 4.2, Task 3.4) | Accepted upstream change; test marker is the old free-text form |
| make-temp-dir-nameerror | make-temp-dir-name-error, temp-dir-collision | forms-convert-utilities.md, import-export-auth.md, models-access-releases-query.md | tests/test_import_export.py, tests/test_query.py, tests/test_utilities.py | K | OPEN |  |
| md-no-escape | — | forms-convert-utilities.md | tests/test_convert.py | S | OPEN | HTML escaping only in S; LaTeX escaping and markdown nesting/first-list-item -> K |
| mutation-via-get | — | views.md, security-audit.md | tests/test_views.py, tests/test_security_audit.py, tests/test_access.py, tests/test_post_only_mutations.py | S | FIXED (Task 6.3) | merge of upstream #86 + POST-only refresh/member add/role validation |
| naive-created-at-default | — | models-access-releases-query.md | tests/test_models.py | K | OPEN |  |
| no-secure-proxy-ssl-header | — | security-audit.md | tests/test_security_audit.py | S | OPEN | optional config key / ROLLOUT operator check |
| order-by-unrestricted | — | security-audit.md | tests/test_security_audit.py | K | OPEN |  |
| owner-empty-names | — | forms-convert-utilities.md | tests/test_utilities.py | K | OPEN |  |
| p-link-selection-lost | — | views.md | tests/test_rendering_snapshots.py | K | OPEN |  |
| redirect-int-parent | — | forms-convert-utilities.md | tests/test_utilities.py | K | OPEN |  |
| ref-link-backslash | — | forms-convert-utilities.md, views.md | tests/test_convert.py, tests/test_rendering_snapshots.py | K | OPEN |  |
| refresh-timestamp-overwritten | — | views.md | tests/test_views.py | K | OPEN |  |
| release-id-unscoped | — | security-audit.md | tests/test_security_audit.py | S | OPEN |  |
| release-version-default-str | — | models-access-releases-query.md | tests/test_models.py | K | OPEN |  |
| s-data-string | — | forms-convert-utilities.md | tests/test_forms.py | K | OPEN |  |
| session-and-reset-hardening | — | security-audit.md | tests/test_security_audit.py | S | OPEN | optional config key / ROLLOUT operator check |
| temp-dir-not-cleaned | — | import-export-auth.md | tests/test_import_export.py | K | OPEN |  |
| temp-files-world-readable | — | security-audit.md | tests/test_security_audit.py | K | OPEN |  |
| tracked-dev-secret-key | — | security-audit.md | tests/test_security_audit.py | S | OPEN | optional config key / ROLLOUT operator check |
| xss-display | — | forms-convert-utilities.md | tests/test_convert.py | S | OPEN |  |
| xss-tag | — | forms-convert-utilities.md | tests/test_convert.py | S | OPEN |  |

## Marker ids not in any doc

none

## Doc ids without a test marker

- add-spec-item-val-set-post
