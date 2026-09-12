# Canvas export

For instructors. Getting grades from the grader into the Canvas gradebook without a Canvas integration.

The grader does not talk to Canvas directly; institutional API access is rarely available, and it keeps Canvas out of the runtime path. Instead it writes a CSV in the exact shape Canvas imports.

## One-time setup

1. Import your Canvas gradebook export on the [Roster](roster-and-staff.md) page at least once. The grader keeps that file as the template: Canvas matches rows on `SIS Login ID` and columns on the header `Assignment name (canvas id)`, and the template supplies both.
2. In each assignment's settings, set `canvas_assignment_id` to the number in the matching Canvas column header. Without it the column is named by title only, and Canvas will ask you to map it on import.

## Export

On the course page, open **Export → Canvas gradebook**, tick the assignments, and download. The file contains every student row from your template with the selected assignment columns filled in and all other columns untouched. Students with no counted attempt get an empty cell, not a zero.

In Canvas, **Import** the file from the gradebook. Canvas previews the changes before applying them. Each export is recorded in the change log.
