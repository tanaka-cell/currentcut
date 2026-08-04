"""The guarded upload path: every cap is enforced server-side.

These tests exercise the guard layer, not the pipeline behind it (the
pipeline has its own tests). The happy path asserts only that a valid upload
starts a run and the status endpoint answers for it.
"""
import subprocess

import pytest


@pytest.fixture()
def client(workdir):
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


@pytest.fixture()
def tiny_mp4(workdir):
    path = workdir / "upload_src" / "tiny.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-f", "lavfi", "-i", "color=c=0x336655:s=160x90:d=1:r=30",
             "-c:v", "libx264", "-preset", "veryfast", str(path)],
            check=True,
        )
    return path


def _post(client, files, title=""):
    return client.post("/api/upload/start", files=files, data={"title": title})


def test_rejects_wrong_extension(client):
    r = _post(client, [("files", ("notes.txt", b"hello", "text/plain"))])
    assert r.status_code == 400
    assert ".mp4" in r.json()["detail"]


def test_rejects_too_many_files(client, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "UPLOAD_MAX_FILES", 2)
    files = [("files", (f"c{i}.mp4", b"x", "video/mp4")) for i in range(3)]
    r = _post(client, files)
    assert r.status_code == 400
    assert "2" in r.json()["detail"]


def test_rejects_oversize_file(client, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "UPLOAD_MAX_FILE_MB", 0)
    r = _post(client, [("files", ("big.mp4", b"x" * 10, "video/mp4"))])
    assert r.status_code == 413


def test_rejects_non_video_content(client, tiny_mp4):
    # Right extension, wrong bytes: ffprobe is the judge, not the filename.
    r = _post(client, [("files", ("fake.mp4", b"this is not video", "video/mp4"))])
    assert r.status_code == 400
    assert "readable video" in r.json()["detail"]


def test_rejects_when_daily_budget_spent(client, monkeypatch, tiny_mp4):
    from app import config
    monkeypatch.setattr(config, "UPLOAD_RUNS_PER_DAY", 0)
    r = _post(client, [("files", ("a.mp4", tiny_mp4.read_bytes(), "video/mp4"))])
    assert r.status_code == 429
    assert "budget" in r.json()["detail"]


def test_rejects_footage_over_duration_cap(client, monkeypatch, tiny_mp4):
    from app import config
    monkeypatch.setattr(config, "UPLOAD_MAX_TOTAL_MINUTES", 0)
    r = _post(client, [("files", ("a.mp4", tiny_mp4.read_bytes(), "video/mp4"))])
    assert r.status_code == 413
    assert "minutes" in r.json()["detail"]


def test_valid_upload_starts_a_run(client, tiny_mp4):
    r = _post(client, [("files", ("mine.mp4", tiny_mp4.read_bytes(), "video/mp4"))],
              title="My shoot")
    assert r.status_code == 200
    project_id = r.json()["project_id"]
    assert project_id.startswith("prj_")

    status = client.get(f"/api/demo/status/{project_id}")
    assert status.status_code == 200
    assert status.json()["state"] in ("running", "done", "failed")


def test_filenames_are_sanitised(workdir):
    from app.upload import _safe_name
    assert _safe_name("../../etc/passwd") == "passwd"
    assert _safe_name("my clip (1).mp4") == "my_clip__1_.mp4"
    assert _safe_name("") == "clip"
