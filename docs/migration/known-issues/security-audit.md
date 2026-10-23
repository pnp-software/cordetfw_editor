# Known issues: security audit (Task 6.2, pinned by tests/test_security_audit.py)

A review of the whole application found the issues below. Each is pinned **as-is** by
a test marked `# KNOWN-ISSUE: <id>` and is not fixed by the migration. Attacker model:
a logged-in user who is a member of project A only (`RO` = read-only, `RW` = write),
or a user without any membership; B is a project they have no access to.

Ids marked (existing) were already recorded; only the extended or narrowed scope is
described here, see the original doc for the rest.

| id | where | current behaviour | minimal role | severity | test |
|----|-------|-------------------|--------------|----------|------|
| `idor-app-valset-cross-project` | utilities.py `get_spec_item_query`, `get_domains`; views.py `list_spec_items`, `export_spec_items` | **FIXED in Task 6.4** (every id is looked up inside the project whose access was checked: foreign id gives 404, see tests/test_scoping_6_4.py). Was: Application-level categories are filtered by `application_id`/`val_set_id` from the URL without checking they belong to the project in the URL. Putting B's ids in an A URL lists and exports B's items (and their domains); the find/replace POST modifies them and makes the user their owner. Project-level categories are not affected (project filter still applies; only the foreign ValSet name leaks). | RO in A | HIGH | `test_01_*` |
| `idor-item-project` (existing, extended) | views.py edit/del/split/refresh/history (about 646, 701, 726, 772, 819, 1160) | **FIXED in Task 6.4** (every id is looked up inside the project whose access was checked: foreign id gives 404, see tests/test_scoping_6_4.py). Was: Beyond the edit form and delete of NEW items (see [models-access-releases-query.md](models-access-releases-query.md)): edit POST modifies B's item (new version, owner changed, `p_link` may point into A); del POST marks B's CNF/MOD item and all its ValSet aliases DEL; split GET/del GET leak the item; split POST creates an item in A linked to B's item (PROTECT blocks its deletion); refresh GET overwrites B's item from the FW Profile DB; history GET needs only read access to A and shows B's item and history. copy is blocked, only because it requires the Default ValSet of the URL project. | RW in A (history: RO) | HIGH | `test_02_*` |
| `idor-parent-link-cross-project` | views.py `add_spec_item` (`s_parent_id`, `p_parent_id`), configs.py `get_p_link_choices`/`get_s_link_choices`, utilities.py `get_redirect_url` | **FIXED in Task 6.4** (every id is looked up inside the project whose access was checked: foreign id gives 404, see tests/test_scoping_6_4.py). Was: The parent item is not checked against the project: B's item is shown in the sub title and as the only `s_link` choice, and the new item of A links to it. B's owner can then no longer delete that item (PROTECT). | RW in A | MEDIUM | `test_03_*` |
| `idor-app-write-cross-project` | views.py add/copy/split/import_spec_items (about 605, 734, 779, 925) | **FIXED in Task 6.4** (every id is looked up inside the project whose access was checked: foreign id gives 404, see tests/test_scoping_6_4.py). Was: A foreign `application_id` is accepted on write: the item is saved with `project=A`, `application=B's app`. It shows up in B's domains, is confirmed by B's application release, and `del_project(B)` fails half-way (ProtectedError after ValSets are deleted). | RW in A | MEDIUM | `test_04_*` |
| `mutation-via-get` (existing, extended) | views.py `refresh_spec_item`, `edit_project` | **FIXED in Task 6.3** (POST-only, role validated, see [views.md](views.md)). Was: `refresh_spec_item` mutated on GET; `edit_project?del_val_set_id=` deletes a ValSet on GET; `?user_id=` without `role` gives an IntegrityError (500); any role string (e.g. `ADMIN`) is stored. See [views.md](views.md). | staff | MEDIUM | `test_05_*` |
| `edit-project-valset-unscoped` | views.py `edit_project` (`del_val_set_id`), `edit_val_set`, `add_val_set` | **FIXED in Task 6.4** (every id is looked up inside the project whose access was checked: foreign id gives 404, see tests/test_scoping_6_4.py). Was: Staff can delete or rename a ValSet of another project through any project URL, and add a second ValSet called `Default`, after which `ValSet.objects.get(name='Default')` raises MultipleObjectsReturned (500) for the project. Same cause as `edit-project-del-user-unscoped` (see [views.md](views.md)). Task 6.3 (upstream #86) already scopes the `del_val_set_id` delete (and `del_user_id`) to the URL's project and makes both POST-only; `edit_val_set` rename and `add_val_set` `Default` are still open (Task 6.4). | staff | LOW | `test_06_*` |
| `release-id-unscoped` | views.py (about 437, 884) | **FIXED in Task 6.4** (every id is looked up inside the project whose access was checked: foreign id gives 404, see tests/test_scoping_6_4.py). Was: `sel_rel_id` of a release of another project is accepted; only its date/version is used as a filter. | RO in A | INFO | `test_07_*` |
| `index-lists-all-projects` | views.py `index` (98), templates/index.html | Every logged-in user sees all projects with description, owner and application names. May be by design. | any user | INFO | `test_08_*` |
| `eval-ref-dos` | convert.py `render_for_eval`/`eval_di_value`; utilities.py:76 | A DataItem `value` is evaluated with cexprtk on every list page and LaTeX export: `while`/`for` loops never finish, `var v[250000000]` allocates 2 GB, and `#iref` fan-out is exponential (11 rows need 2046 queries); about 1200 refs raise RecursionError (not tested, slow). One worker is pinned per request. | RW in A (victims: any reader) | MEDIUM-HIGH | `test_09_*` |
| `iref-cross-project-disclosure` | convert.py (64-70, 233, 253, 285); `convert_edit_to_db` passes `#iref:<id>` through | A literal `#iref:<foreign id>` can be stored through form/CSV/ZIP import. Display, edit, LaTeX and eval then resolve it without a project check and disclose B's `domain:name`, the tooltip (title, desc, value) and the evaluated value. | RW in A | MEDIUM | `test_10_*` |
| `latex-export-injection` | convert.py 36-49 `frmt_string`; utilities.py:76 | `\ { } $` are not escaped and NVal is not escaped at all, so `\input{...}` / `\write18` reach the exported LaTeX. Only dangerous if the export is compiled with shell-escape or from a trusted directory. A fix changes export bytes. | RW in A (victim: whoever compiles) | LOW-MEDIUM | `test_11_*` |
| `order-by-unrestricted` | utilities.py 513-514; views 430, 873 | `?order_by=` is passed to `.order_by()`: `owner__password`, `owner__email`, `owner__is_superuser` are accepted, giving a sort-order oracle on user data. (Invalid names give 500, see `list-500s`.) | RO in A | LOW | `test_12_*` |
| `csv-formula-injection` | utilities.py 91-107, resources.py | Exported cells starting with `=`, `+`, `-`, `@` are written as-is. A fix changes export bytes. | RW in A (victim: spreadsheet user) | LOW | `test_13_*` |
| `link-suggest-js-string` | editor/templates/link_suggest.html:6 | A title ending in a backslash or containing a newline breaks the inline JS string (autocomplete is broken for the whole project). Quotes and tags are HTML-escaped, so not XSS. | RW in A | LOW | `test_14_*` |
| `import-traceback-in-message` | views.py (about 1049) | `traceback.format_exc()` is shown to the user as a message, disclosing server file paths. | RW in A | LOW | `test_15_*` |
| `ext-cats-sql-injection` (existing, narrowed) | ext_cats.py 137, 178 | Only `request.user.email` is attacker-controlled: ids are int- or choice-validated. Django's `EmailValidator` accepts `x'or+1#@a.com`, which is spliced into the SQL. See [import-export-auth.md](import-export-auth.md). | any user editing their e-mail (staff or admin) | MEDIUM | `test_16_*`, tests/test_ext_cats.py |
| `no-secure-proxy-ssl-header` | settings.py | `SECURE_PROXY_SSL_HEADER` is not set: behind a TLS-terminating proxy `is_secure()` is False and absolute links (password reset) are `http://`. | operator | conditional | `test_17_*` |
| `axes-ip-only-lockout` | settings.py (axes defaults) | Lockout is by `REMOTE_ADDR` only (3 failures): distributed guessing of one account is unlimited, and behind a proxy (X-Forwarded-For ignored) everybody shares one counter. | anonymous | MEDIUM conditional | `test_18_*` |
| `tracked-dev-secret-key` | dj_cordetfw_config.json | The file is tracked in git with a `SECURE_KEY` and `DEBUG: true`; dangerous if production was ever seeded from it. | operator | MEDIUM | `test_19_*` |
| `temp-files-world-readable` | utilities.py `make_temp_dir`; configs.json `temp_dir` | Exports/imports are left in the temp dir (default `/tmp`) as 0755/0644 with predictable timestamp names. A pre-created directory gives a 500 (same NameError as `make-temp-dir-nameerror`, not re-tested). | local user | LOW-MEDIUM | `test_20_*` |
| `import-project-no-limits` | views.py 1074-1082 | Staff-only ZIP import: no limits on size or member count (a 20 MB member compresses to about 20 KB); `extractall` is used (zip-slip is neutralised on Python 3.12). | staff | LOW | `test_21_*` |
| `import-project-attribution-forgery` | imports.py | Staff-only: owner, release author, `cat` and `status` from the CSV are not validated; bad values cause later 500s (`spec_item_to_edit` KeyError). | staff | LOW | `test_22_*` |
| `session-and-reset-hardening` | settings.py | Defaults: sessions last two weeks, no CSP, no HSTS and no SSL redirect configured in the app. | operator | INFO | `test_23_*` |

## Operator checks (before cutover)

- `no-secure-proxy-ssl-header`: if TLS ends at a proxy, set `SECURE_PROXY_SSL_HEADER` (and
  make the proxy strip the client's `X-Forwarded-Proto`), otherwise password reset mails contain `http://` links.
- `axes-ip-only-lockout`: decide on `AXES_LOCKOUT_PARAMETERS` (e.g. `[["ip_address", "username"]]`) and
  make sure axes sees the real client IP behind the proxy (e.g. `AXES_IPWARE_PROXY_COUNT`/trusted header).
- `tracked-dev-secret-key`: confirm that `/etc/dj_cordetfw_config.json` has its own `SECURE_KEY`,
  `DEBUG: false`, and that the key in git is not the production key (rotate otherwise).
- `session-and-reset-hardening`: consider `SESSION_COOKIE_AGE`, HSTS (`SECURE_HSTS_SECONDS`), a CSP header
  at the proxy, and `SECURE_SSL_REDIRECT` if the proxy does not redirect.
- Run `pip-audit -r requirements-lock.txt` before cutover and review the result.

## Checked and found safe

- ZIP import: member names such as `../escape.txt` are neutralised by `extractall` on Python 3.12
  (pinned in `test_21_import_project_no_limits`).
- Messages are autoescaped by Django templates (no XSS through `messages`).
- No open redirect: `next` parameters go through Django's host check (see `logout-unsafe-next-self-redirect`).
- No `.raw()`/`.extra()` outside `editor/ext_cats.py`; the ORM is used everywhere else.
- CSRF is enforced on all POST views (GET mutations are listed above).
- The JS in `link_suggest.html` is HTML-escaped: quotes and tags cannot break out (only backslash/newline break it).
