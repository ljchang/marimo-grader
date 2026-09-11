from tests.conftest import login, notebook_token


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"]


def test_unauthenticated_me(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


def test_dev_login_sets_session_and_me(client, seed):
    login(client, "f00abc1")
    me = client.get("/api/v1/auth/me").json()
    assert me["netid"] == "f00abc1"
    assert me["enrollments"][0]["role"] == "student"
    assert me["enrollments"][0]["course_slug"] == "neuroimaging"


def test_csrf_required_on_mutations(client, seed):
    login(client, "prof")
    r = client.post(
        f"/api/v1/offerings/{seed.offering_id}/assignments", json={"slug": "x", "title": "X"}
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf"


def test_device_handshake_and_bearer(client, seed):
    token = notebook_token(client, "f00abc1")
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["via"] == "token" and r.json()["netid"] == "f00abc1"


def test_device_code_single_use(client, seed):
    start = client.post("/api/v1/auth/device", json={}).json()
    login(client, "f00abc1")
    assert client.get(f"/api/v1/auth/device/verify?code={start['user_code']}").status_code == 200
    # second approval of the same code fails
    assert client.get(f"/api/v1/auth/device/verify?code={start['user_code']}").status_code == 400
    tok = client.post(
        "/api/v1/auth/device/token", json={"device_code": start["device_code"]}
    ).json()
    assert tok["status"] == "approved"
    again = client.post(
        "/api/v1/auth/device/token", json={"device_code": start["device_code"]}
    ).json()
    assert again["status"] == "expired"


def test_bad_bearer_rejected(client, seed):
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_token"


def test_login_next_must_be_relative(client, seed):
    r = client.get("/api/v1/auth/login?next=https://evil.example/", follow_redirects=False)
    assert r.status_code == 307 or r.status_code == 302
    assert "evil.example" not in r.headers["location"]
