# Change log

For instructors. Every action that can affect a grade or who is in the course is recorded, so a dispute or a mistake can be traced.

This is the page of that name *inside the grader* — an audit trail of your course. The project's release notes are the separate [Changelog](../changelog.md) in the nav.

It is not part of the daily navigation; it is linked from the roster page and from each student's history page. It lists, newest first:

| Recorded action | What the entry shows |
|---|---|
| Score saved or changed | who, when, the total before and after, whether it was released, the reason if one was given |
| Roster import applied | counts added, dropped, moved, and the NetIDs |
| Teaching staff added or changed | NetID, role, sections |
| Assignment created or its settings changed | the settings before and after |
| Assignment version published | version number and question ids |
| Canvas export | which assignments |
| Submission re-queued for grading | student and question |

Entries are append-only. Filter by NetID, entity, action, or reason.

Platform administrators have their own log of platform-level events (courses, offerings, staff, publishes, imports, exports). It deliberately excludes score changes: administrators do not see student work. If an administrator needs a course's grade history, they add themselves as an instructor of that offering, and that action is itself logged.
