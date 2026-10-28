import io
import time
import zipfile

from fastapi.testclient import TestClient
from PIL import Image

from arturokai import server


class FakeImage:
    def generate(self, prompt, negative, w, h, steps, seed, count):
        paths = []
        for i in range(count):
            p = server.OUT / f"test_img_{i}.png"
            Image.new("RGB", (8, 8)).save(p)
            paths.append(p)
        return paths


class FakeVideo:
    def generate(self, prompt, seconds, negative, start, seed, steps, progress):
        progress(0.5, desc="Сегмент 1/2")
        p = server.OUT / "test_vid.mp4"
        p.write_bytes(b"0")
        return p


server._gens.update(image=FakeImage(), video=FakeVideo())
client = TestClient(server.app)


def wait(job_id):
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.05)
    raise AssertionError("задача не завершилась")


def test_site_served():
    r = client.get("/")
    assert r.status_code == 200 and "ARTurokAI" in r.text
    assert client.get("/static/app.js").status_code == 200


def test_image_job():
    job = client.post("/api/image", json={"prompt": "кот", "count": 2}).json()
    done = wait(job["id"])
    assert done["status"] == "done" and len(done["result"]) == 2
    assert client.get(done["result"][0]).status_code == 200


def test_video_job_with_start_image():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, "PNG")
    name = client.post("/api/upload-image", files={"file": ("a.png", buf.getvalue())}).json()["name"]
    job = client.post("/api/video", json={"prompt": "горы", "seconds": 120, "start_image": name}).json()
    assert wait(job["id"])["result"] == ["/outputs/test_vid.mp4"]


def test_validation():
    assert client.post("/api/image", json={"prompt": ""}).status_code == 422
    assert client.post("/api/video", json={"prompt": "x", "seconds": 121}).status_code == 422


def test_zip_and_export():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("src/main.py", "print(1)")
    d = client.post("/api/zip", files={"file": ("p.zip", buf.getvalue())}).json()
    assert "main.py" in d["tree"] and "print(1)" in server.projects[d["project_id"]]

    r = client.post("/api/export", json={"text": "```python a.py\nx=1\n```"})
    assert r.headers["content-type"] == "application/zip"
    assert client.post("/api/export", json={"text": "нет кода"}).status_code == 400
    assert client.post("/api/zip", files={"file": ("bad.zip", b"not a zip")}).status_code == 400
