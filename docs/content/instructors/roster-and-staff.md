# Roster and staff

For instructors. Who is in the course, and who may grade it.

Students are never typed in by hand. The roster page imports a file, shows you exactly what would change, and applies it only when you confirm. Every import is recorded in the change log.

## Import from Canvas

1. In Canvas, open the gradebook and choose **Export → Export Entire Gradebook**. You get a CSV with `Student`, `ID`, `SIS User ID`, `SIS Login ID`, `Section`, and one column per assignment.
2. On the grader's Roster page, choose the file, select **Canvas CSV**, and press **Preview changes**.
3. Review the four lists: students to add, students to drop, section moves, and rows that could not be matched. Untick anything you do not want applied.
4. Press **Apply**.

![The roster page: import from Canvas or Banner, add teaching staff, and the current roster](../images/roster.png)

Matching uses the SIS Login ID, which is the NetID at Dartmouth. The upload is also kept as the template for [Canvas export](canvas-export.md), so the first import doubles as setup for grade export.

## Import from Banner

Download the class list from Banner self-service as CSV (save Excel exports as CSV first), choose **Banner** as the source, and continue as above. Column names vary between institutions, so the importer looks for anything resembling a NetID or username, an email, a name, and a section or CRN. Rows without a usable identifier appear in the unmatched list.

## Drops

Dropping never deletes anything. A dropped student keeps every submission and grade, loses access to submitting and to the portal, and disappears from the roster grid. Re-importing a roster that includes them reactivates the enrollment.

## Teaching staff

The **Teaching staff** form on the roster page adds a TA or a co-instructor by NetID. The person does not need to have signed in before; their account is created and matched when they arrive through single sign-on.

- An **instructor** sees and can change everything in the offering.
- A **TA** can view submissions and grade. Leave the sections field empty to let them grade the whole class, or list section names to restrict them to those sections: they will not see other sections' students, submissions, or history.
- Whether a TA's scores are released to students directly is an offering setting (`ta_can_finalize`, on by default).

Only platform administrators can create courses and offerings and name the first instructor. After that, instructors manage their own staff.
