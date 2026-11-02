# Why do production spec items have empty "required" fields?

Analysis (2026-10-24) of the 447 spec-item rows that the CSV importer rejects as "missing required field"
(`csv-export-not-reimportable`; production dump 2026-10-21, production code `cd87ccb`). Aggregates only: counts,
categories, field names, months, statuses and project ranks.

## Short answer

`req_in_form` is enforced **only by the spec-item web form** (add / edit / copy / split). Until commit `b4bf39d`
(2026-09-18) the **category CSV import** wrote rows without any required-field check.

- **446 rows** were last written by a **bulk CSV import** (many items in the same few seconds, one user), and none was
  edited through the form afterwards.
- **1 row** (a Packet): the field became required after the item already existed.
- Ruled out: Find & Replace, project ZIP import, admin, data migrations, FW Profile refresh, copy/split.

## 1. The empty fields (live items, status not DEL/OBS)

All empty values are `''` (none whitespace-only). A null link is exported as `None`, so it never counts as empty.

| Category | Rows | Empty required field(s) (CSV label) |
|---|---|---|
| Requirement | 399 | `s_kind` (Ver): 399, of which 13 also `value` (Text) |
| DataItem | 31 | `value` (Value) |
| SysReq | 8 | `p_kind` (Compl) and `s_kind` (Ver), always both |
| Packet | 7 | `t2` (Destination): 6, `p_kind` (Kind): 1 |
| DerPacket | 2 | `t1` (Parameters) |

Status: all CNF except 4 SysReq still NEW. Domain, name, title and the required links are filled everywhere.

## 2. When the fields became required (configs.json history)

| Category | Field | Required since |
|---|---|---|
| Requirement | value, p_kind, s_kind | before the data existed (`configs.py` before `7b34681`, 2021-04) |
| DataItem | value | 2021-04 |
| SysReq | p_kind, s_kind | category created with them required (`51501e5`, 2021-10-20) |
| Packet | t1, t2 | 2021-04 (`7b34681`) |
| Packet | **p_kind** | **2022-09-29** (`7cc2b82` "Added TM/TC kind to packets") |
| DerPacket | t1, s_link, p_link | 2021-04 (`7b34681`/`339cc1f`) |

Apart from Packet `p_kind`, every affected field was already required when the items were written.

## 3. Write paths that bypass `req_in_form` (code at `cd87ccb` and earlier)

| Path | Enforces req_in_form? | Notes |
|---|---|---|
| Add / edit / copy / split form | yes | text fields `required=True`; select fields: see section 5 |
| Category CSV import | **no** before `b4bf39d` (2026-09-18) | since 2021-02; an empty cell gives an empty field |
| Project ZIP import | no | no project in the dump shows a ZIP-import pattern |
| Find & Replace | effectively yes | `replace` is a required, stripped field (since 2023-04) |
| FW Profile refresh | no | only Model/FCP, not these categories |
| Release | n/a | status only |
| Admin | n/a | `django_admin_log` has no SpecItem changes |
| Data migrations | n/a | none touch these fields |

## 4. Evidence per group (bulk-write signature)

"Batch" = items of the same category and project with `updated_at` within ±2 minutes of the empty items.

| Group | Rows | Last write | Batch | Cause |
|---|---|---|---|---|
| Requirement, project rank 3 of 9 | 399 | 2022-10, ~10 s, 1 user | 399 | CSV import of new items with empty Ver (13 also empty Text) |
| DataItem, rank 3 | 29 | 2022-09, ~5 s | 217 | CSV re-import (in-place update); empty since the 2021-04 bulk load |
| Packet, rank 3 | 6 | 2022-09-29, ~10 min after `7cc2b82` | 90 | CSV re-import to fill the new Kind; Destination stayed empty since 2021-04 |
| Packet, rank 4 | 1 | 2022-02 | 1 | Kind added later (2022-09-29), item never edited since |
| DerPacket, rank 3 | 2 | 2021-04-30 | 10 | CSV import of new items |
| SysReq, rank 4 | 4 | 2021-10-20, ~30 min after the category was added | 4 | CSV import of new items (looks like a first test; still NEW) |
| SysReq, rank 1 | 4 | 2025-04 | 86 | CSV import of new items, 4 of 86 rows without Compl/Ver |
| DataItem, rank 1 | 2 | 2025-01 | 10 | CSV import of new items, 2 of 10 rows without Value |

436 of the 447 rows (98 %) are in one project; 434 were last written in 2021–2022. In the Requirement block of about
500 items imported in 2022-10, the 99 items edited since then all have Ver filled now.

## 5. What happens when such an item is edited today

- **Text fields** (Requirement/DataItem `value`, Packet `t2`, DerPacket `t1`): the form says "This field is required"
  and saves only after the user fills it.
- **Choice fields** (Requirement Ver, SysReq Compl/Ver, Packet Kind): the select has no blank option and `''` matches
  no choice, so the browser shows and submits the **first choice** (`TST` for Ver, `C` for Compl, `TC` for Kind). The
  edit saves that value **without notice** unless the user changes it. This probably is how the 99 edited
  Requirements got their Ver. New register row: `form-choice-empty-silent-default`.

## Consequences for track K

- Operator decision 2026-10-24: the CSV importer accepts empty required fields again and lists those rows as
  warnings in the import summary (the edit form still requires them).
- Data clean-up (owners choosing the missing values) is optional and not automated.

Data hygiene: the dump was streamed into a throwaway database on the disposable test container and dropped after the
aggregate queries; no decompressed file was written; no other database was accessed.
