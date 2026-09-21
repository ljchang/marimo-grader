# Course storage

Students' notebooks can read the course's own data and keep their own files, with nothing to configure and no credential they can leak. The grader is what makes that safe: a signed-in notebook asks it for storage, and it hands back short-lived credentials that reach exactly the prefixes that enrollment is entitled to — nothing else in the bucket.

This page is for instructors: what students get, how to put data in, and what the audit shows. The design is in [the storage design document](../../storage-architecture.md); the Cloudflare setup is in [Deploy and operate → Storage](../operators/storage.md).

## What a student gets

One bucket holds everything, partitioned by prefix. A signed-in student's notebook receives two credentials, valid for an hour and renewed for as long as their sign-in lasts:

| In the notebook | What it is | Student | You |
|---|---|---|---|
| `storage.course()` | the class's own data | read | read, write |
| `storage.assignment("midterm")` | data for one assignment, from its `release_at` | read | read, write |
| `storage.private()` | that student's own space | read, write | read (`/students`) |
| `storage.group()` | a project group's space | members read, write | read, write |
| `@storage.cache` | results computed once, reused later | own cache; reads a shared one | writes the shared one |

Public datasets — `storage.dataset("localizer")` and the existing `dartbrains_tools.data` loaders — stay on Hugging Face and need no sign-in.

A student's prefix is named by an opaque id (an HMAC of their NetID), so a listing never shows who else is in the course. Every credential the grader hands out is recorded in the `storage_grants` table: who, which prefixes, when, from which runtime.

The chapter side looks like this, and works the same for a reader who is not enrolled — they just never click the button and the chapter falls back to public data:

```python
signin = storage.signin_button(); signin
course = storage.course() if storage.connect(signin) else None
```

## Putting class data in

You do not need Cloudflare credentials. As an instructor your `storage.course()` mount is read-write, so from any signed-in notebook or a local Python session:

```python
from dartbrains_tools import storage
storage.signin()                                    # device sign-in, cached afterwards

course = storage.course()
course.put("localizer/README.md", "What this copy contains ...")
course.upload("~/data/sub-S01_bold.nii.gz", "localizer/sub-S01/func/sub-S01_bold.nii.gz")
course.sync("~/data/localizer", "localizer")        # rsync-like: adds and updates, never deletes
course.ls()
```

Keep the layout of the public dataset when you mirror it (`localizer/<the same relative path>`), so a chapter can address both copies with `localizer.filename(...)` and only the root differs.

Assignment data goes under its slug: `storage.assignment("midterm").put(...)`. Students cannot see it until the assignment's `release_at`, and not after `close_at` — both are assignment settings, editable through `PATCH /offerings/{id}/assignments/{id}` (`{"settings": {"release_at": "2026-11-04T09:00:00-05:00"}}`). Before release the prefix is simply absent from every credential the grader mints, so the data is unreachable rather than hidden; a change takes effect for everyone within the hour and immediately for a revoked sign-in.

## Seeing what students stored

`storage.mount("/students")` lists every student's area under their opaque id. To find one student, `storage.mount("/students").ls()` and match on what they saved; the grader's audit maps ids to NetIDs when you need that. A TA scoped to sections sees only those sections' students.

## Groups

The grader has `groups` and `group_members` tables and the broker grants `/group` to members, but there is no roster UI or CSV import yet — creating groups is a database step for now.

## Limits worth knowing

- **Autograding.** The grader's sandbox has no network, so an assignment that reads course storage cannot be autograded until the worker learns to stage those files (planned; see the design document). Assignments that only *write* to private storage are fine — the submission is the artifact.
- **The in-browser editor.** The site's edit view (the notebook running inside the page) has no storage backend yet; chapters fall back to public data there and say so. molab and laptops have full storage.
- **Copying course data into a private area** goes through the student's kernel, not server-side: no single credential can read the source and write the destination.
- **Rotating `GRADER_STORAGE_UID_SECRET`** moves every student to a fresh, empty prefix. Only ever do that between terms.
