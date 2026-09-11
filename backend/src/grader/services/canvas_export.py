"""Canvas gradebook CSV export.

Canvas imports grades by matching rows on ``SIS Login ID`` (NetID at Dartmouth)
and columns on the exact header ``Assignment Name (canvas_id)``. The instructor
uploads their current Canvas gradebook export once (stored as a roster upload);
we re-emit its student rows with the selected assignment columns filled in and
every other column untouched, which is the shape Canvas accepts back.
"""

from __future__ import annotations

import csv
import io

IDENTITY_COLUMNS = ("Student", "ID", "SIS User ID", "SIS Login ID", "Section")


def build_canvas_csv(
    template_csv: str,
    columns: dict[str, dict[str, float | None]],
) -> str:
    """``columns`` maps a Canvas header (``"GLM (12345)"``) to ``{netid: points}``."""
    reader = csv.DictReader(io.StringIO(template_csv))
    headers = list(reader.fieldnames or [])
    for h in columns:
        if h not in headers:
            headers.append(h)
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in reader:
        student = (row.get("Student") or "").strip()
        login = (row.get("SIS Login ID") or "").strip().lower()
        netid = login.split("@", 1)[0] if login else ""
        if student.lower() in ("points possible", "student, test", "test student"):
            writer.writerow(row)
            continue
        for h, grades in columns.items():
            if netid in grades and grades[netid] is not None:
                row[h] = f"{grades[netid]:g}"
            else:
                row.setdefault(h, "")
        writer.writerow(row)
    return out.getvalue()


def header_for(title: str, canvas_assignment_id: str | int | None) -> str:
    return f"{title} ({canvas_assignment_id})" if canvas_assignment_id else title
