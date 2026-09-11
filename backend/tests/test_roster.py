import io

from grader.services.roster import parse_banner, parse_canvas_csv, parse_simple
from tests.conftest import login

CANVAS = (
    "Student,ID,SIS User ID,SIS Login ID,Section,GLM (12345)\n"
    "    Points Possible,,,,,10\n"
    '"Student, Alice",11,S1,f00abc1,NEUR 01,\n'
    '"New, Carol",13,S3,F00NEW1@dartmouth.edu,NEUR 02,\n'
    '"Student, Test",99,,,NEUR 01,\n'
)

BANNER = (
    "Banner ID\tStudent Name\tEmail\tCRN\n"
    "A0001\tStudent, Alice\tAlice.Student@dartmouth.edu\t12345\n"
    "A0002\tDoe, Dan\tdan.doe@dartmouth.edu\t12345\n"
    "A0003\tNo Email\t\t12345\n"
)


def test_parse_canvas():
    rows = parse_canvas_csv(CANVAS)
    assert [r.netid for r in rows] == ["f00abc1", "f00new1"]
    assert rows[1].display_name == "Carol New" and rows[1].section == "NEUR 02"


def test_parse_banner_tab_separated():
    rows = parse_banner(BANNER)
    assert rows[0].netid == "alice.student" and rows[0].display_name == "Alice Student"
    assert rows[2].netid == "" and rows[2].raw_id == "A0003"


def test_parse_simple():
    rows = parse_simple("netid,name,section\nf00a,Alice,01\nf00b,,\n")
    assert [(r.netid, r.display_name, r.section) for r in rows] == [
        ("f00a", "Alice", "01"),
        ("f00b", None, None),
    ]


def test_preview_then_apply(client, seed):
    csrf = login(client, "prof")
    r = client.post(
        f"/api/v1/offerings/{seed.offering_id}/roster/preview",
        files={"file": ("grades.csv", io.BytesIO(CANVAS.encode()), "text/csv")},
        data={"source": "canvas_csv"},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200, r.text
    plan = r.json()
    assert {a["netid"] for a in plan["adds"]} == {"f00new1"}
    assert {d["netid"] for d in plan["drops"]} == {"f00xyz9"}
    assert {m["netid"] for m in plan["moves"]} == {"f00abc1"}  # section None -> NEUR 01
    assert plan["unmatched"] == []

    r = client.post(
        f"/api/v1/offerings/{seed.offering_id}/roster/apply",
        json=plan,
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200 and r.json() == {"added": 1, "dropped": 1, "moved": 1}
    roster = {
        e["netid"]: e for e in client.get(f"/api/v1/offerings/{seed.offering_id}/roster").json()
    }
    assert roster["f00xyz9"]["status"] == "dropped"
    assert roster["f00new1"]["section"] == "NEUR 02" and roster["f00abc1"]["section"] == "NEUR 01"
    # dropped students keep their enrollment row; re-importing re-activates them
    r = client.post(
        f"/api/v1/offerings/{seed.offering_id}/roster/apply",
        json={"adds": [{"netid": "f00xyz9"}]},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.json()["added"] == 1


def test_ta_cannot_import(client, seed):
    csrf = login(client, "ta1")
    r = client.post(
        f"/api/v1/offerings/{seed.offering_id}/roster/apply",
        json={"adds": []},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 403


def test_add_staff_scoped_ta(client, seed):
    csrf = login(client, "prof")
    r = client.post(
        f"/api/v1/offerings/{seed.offering_id}/roster/staff",
        json={"netid": "ta2", "role": "ta", "ta_sections": []},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 201 and r.json()["role"] == "ta"
