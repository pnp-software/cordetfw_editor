# Data impact of `add-app-releases-null-app-items` (fixed in Task 6.5)

Until Task 6.5, adding an application ran `do_application_release` on the unsaved application, so
`SpecItem.objects.filter(application_id=None)` matched the project-level items (no application) of **all
projects** and set every NEW/MOD one to CNF. `updated_at` was not changed, and no history row was written.

Operator decision (2026-10-23): **report only**. No automatic repair; project owners check the items listed
by the query below and re-edit them where needed.

## How affected items are recognised

Only two code paths set `status = 'CNF'`: `do_project_release` and `do_application_release`
(`editor/utilities.py`). A regular project release confirms project-level items **without** changing their
`updated_at`, and the release's own `updated_at` is later than every item it confirms. The release views
rely on this (`get_spec_item_query` hides CNF items with `updated_at` after the selected release).

So a project-level CNF item whose `updated_at` is **after its project's current release** cannot come from
a project release; it was confirmed by the application-creation bug. (The only other theoretical source is a
project ZIP import, which takes status and timestamps from the CSV.) The status before the bug can be read
from the item: `previous` empty → it was **NEW**, `previous` set → it was **MOD**.

## Production dump of 2026-10-21 (aggregates only)

| | |
|---|---|
| Affected items | 80 (74 were NEW, 6 were MOD) |
| Affected projects | 4 of 9 (counts by project, ordered by id: 5, 63, 1, 11) |
| Consistent with a later application creation | 80 of 80 (each item was last edited before an "Initial release for application …", 10 such events between 2023-09-10 and 2025-04-08) |
| Projects where all CNF items are affected | 2 (63 of 63 and 11 of 11: apparently never released, their items were confirmed only by applications being added) |

Effects on users: these items show as CNF instead of NEW/MOD, so they no longer appear as pending changes,
and release views that filter CNF items by date treat them inconsistently.

## Read-only query for the operator

Run on production (or a fresh dump) with a read-only account. It lists the affected items with the status
they most likely had. Do not commit its output (it contains project data).

```sql
SELECT p.name                                   AS project,
       i.cat, i.domain, i.name, i.title,
       i.updated_at                             AS item_updated,
       r.updated_at                             AS project_release,
       IF(i.previous_id IS NULL, 'NEW', 'MOD')  AS probable_status
FROM editor_specitem i
JOIN editor_project p ON p.id = i.project_id
JOIN editor_release r ON r.id = p.release_id
WHERE i.application_id IS NULL
  AND i.status = 'CNF'
  AND i.updated_at > r.updated_at
ORDER BY p.name, i.cat, i.domain, i.name;
```

Editing a CNF item in the editor turns it into MOD (with an OBS copy of the previous version), which brings
it back into the change set of the next release. An item that was NEW cannot be made NEW again through the UI;
the owner decides whether MOD is acceptable for it.
