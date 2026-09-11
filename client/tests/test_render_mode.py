from grader_client import Grader


def test_widgets_become_placeholders_in_render_mode(monkeypatch):
    monkeypatch.setenv("GRADER_RENDER", "1")
    g = Grader(server="http://x", assignment_version_id="v", source="# /// script\n# ///\n")
    for obj in (g.signin_button(), g.submit_button("glm-q01"), g.feedback("glm-q01")):
        html = obj.text if hasattr(obj, "text") else obj._repr_html_()
        assert "hidden in rendered view" in html
    assert "Submit glm-q01" in (
        g.submit_button("glm-q01").text
        if hasattr(g.submit_button("glm-q01"), "text")
        else g.submit_button("glm-q01")._repr_html_()
    )


def test_widgets_are_real_outside_render_mode(monkeypatch):
    monkeypatch.delenv("GRADER_RENDER", raising=False)
    g = Grader(server="http://x", assignment_version_id="v", source="# /// script\n# ///\n")
    w = g.submit_button("glm-q01")
    assert w.mode == "submit" and w.question_id == "glm-q01"
