"""Offline tests for the wan3 package: request bodies, limits, the job lifecycle and the CLI."""
import io
import json
import os
import sys
import urllib.error

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wan3 import Shot, Wan3, Wan3Error, price  # noqa: E402
from wan3 import client as wan_client  # noqa: E402
from wan3.__main__ import main as cli  # noqa: E402


class Body(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class Seen(list):
    """Requests in arrival order, plus the scripted status replies."""


@pytest.fixture
def server(monkeypatch):
    """Install a scripted fake of the three endpoints; returns the list of seen requests."""
    seen = Seen()
    script = {"status": [{"status": "pending", "progress": 12}, {"status": "done", "usage": {"billed_seconds": 12}}]}

    def urlopen(req, timeout=None):
        seen.append(req)
        if req.full_url.endswith("/videos/generations"):
            return Body(b'{"request_id": "r-9"}')
        if req.full_url.endswith("/videos/r-9/content"):
            return Body(b"MP4DATA")
        if req.full_url.endswith("/videos/r-9"):
            return Body(json.dumps(script["status"].pop(0)).encode())
        if req.full_url.endswith("/media/uploads"):
            return Body(b'{"upload_url": "https://bucket.test/u", "media_url": "https://cdn.test/m.mp4"}')
        if req.full_url == "https://bucket.test/u":
            return Body(b"")
        raise AssertionError(req.full_url)

    monkeypatch.setattr(wan_client.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(wan_client.time, "sleep", lambda _: None)
    seen.script = script
    return seen


def test_text_body_defaults():
    assert Shot("fog over a lake").body() == {
        "model": "wan-3", "prompt": "fog over a lake", "resolution": "720p", "duration": 5, "aspect_ratio": "16:9"}


def test_wan3_accepts_2_to_30_seconds_and_three_tiers():
    assert Shot("x", duration=2, resolution="480p").body()["duration"] == 2
    assert Shot("x", duration=30, resolution="1080p").body()["resolution"] == "1080p"
    for bad in (dict(duration=1), dict(duration=31), dict(resolution="768p"), dict(resolution="4k")):
        with pytest.raises(Wan3Error):
            Shot("x", **bad).body()


def test_frames_default_to_adaptive_but_may_crop_to_a_fixed_ratio():
    assert Shot("x", start_image="https://a.test/f.png").body()["aspect_ratio"] == "adaptive"
    assert Shot("x", start_image="https://a.test/f.png", aspect_ratio="9:16").body()["aspect_ratio"] == "9:16"
    with pytest.raises(Wan3Error, match="cannot be mixed"):
        Shot("x", start_image="https://a.test/f.png", images=["https://a.test/r.png"]).body()


def test_audio_alone_is_a_valid_reference_on_wan3():
    body = Shot("dance to @Audio 1", audios=["https://a.test/song.mp3"]).body()
    assert body["reference_audios"] == [{"url": "https://a.test/song.mp3"}]


def test_reference_caps():
    full = Shot("x", images=["https://a.test/i.png"] * 10, videos=["https://a.test/v.mp4"] * 5,
                audios=["https://a.test/a.mp3"] * 5, aspect_ratio="adaptive").body()
    assert len(full["reference_images"]) + len(full["reference_videos"]) + len(full["reference_audios"]) == 20
    for too_many in (dict(images=["https://a.test/i.png"] * 11), dict(videos=["https://a.test/v.mp4"] * 6),
                     dict(audios=["https://a.test/a.mp3"] * 6)):
        with pytest.raises(Wan3Error):
            Shot("x", **too_many).body()
    with pytest.raises(Wan3Error, match="https"):
        Shot("x", images=["file:///tmp/a.png"]).body()


def test_edit_body_leaves_out_duration_and_ratio():
    body = Shot("make it night", edit=True, videos=["https://a.test/clip.mp4"], seed=3, sound=False).body()
    assert body["omni_reference_task_type"] == "edit"
    assert "duration" not in body and "aspect_ratio" not in body
    assert body["seed"] == 3 and body["generate_audio"] is False
    with pytest.raises(Wan3Error):
        Shot("x", edit=True, videos=["https://a.test/clip.mp4"], duration=5).body()
    with pytest.raises(Wan3Error):
        Shot("x", edit=True).body()


def test_seed_range():
    assert Shot("x", seed=4_294_967_295).body()["seed"] == 4_294_967_295
    for bad in (-1, 4_294_967_296, True, 1.5):
        with pytest.raises(Wan3Error):
            Shot("x", seed=bad).body()


def test_price_counts_reference_video_and_edits_twice():
    assert price(10, "720p") == pytest.approx(0.75)
    assert price(5, "480p", reference_video_seconds=2.4) == pytest.approx(7 * 0.038)
    assert price(6, "720p", reference_video_seconds=6) == pytest.approx(0.90)


def test_run_submits_polls_and_saves(server, tmp_path):
    job = Wan3(api_key="key").run(Shot("x", duration=12), str(tmp_path / "a.mp4"))
    assert job["usage"]["billed_seconds"] == 12
    assert [r.full_url.rsplit("/v1", 1)[1] for r in server] == [
        "/videos/generations", "/videos/r-9", "/videos/r-9", "/videos/r-9/content"]
    assert server[0].get_header("Authorization") == "Bearer key"
    assert {r.get_header("User-agent") for r in server} == {"wan-3-0-api/1.0"}
    assert (tmp_path / "a.mp4").read_bytes() == b"MP4DATA"


def test_failed_job_raises_with_body(server):
    server.script["status"] = [{"status": "failed", "error": {"code": "invalid_input", "retryable": False}}]
    with pytest.raises(Wan3Error, match="invalid_input") as err:
        Wan3(api_key="key").wait("r-9")
    assert err.value.body["status"] == "failed"


def test_http_error_is_wrapped(monkeypatch):
    def deny(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 402, "Payment Required", {}, io.BytesIO(b'{"error":{"message":"balance"}}'))

    monkeypatch.setattr(wan_client.urllib.request, "urlopen", deny)
    with pytest.raises(Wan3Error) as err:
        Wan3(api_key="key").submit(Shot("x"))
    assert err.value.http_status == 402


def test_upload_sends_type_and_size(server, tmp_path):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"0123456789")
    assert Wan3(api_key="key").upload(str(clip)) == "https://cdn.test/m.mp4"
    assert json.loads(server[0].data) == {"model": "wan-3", "type": "video", "content_type": "video/mp4", "size_bytes": 10}
    assert server[1].get_method() == "PUT" and server[1].get_header("Authorization") is None
    assert server[1].get_header("User-agent") == "wan-3-0-api/1.0"


def test_cli_dry_run_uses_placeholders_and_sends_nothing(monkeypatch, capsys):
    monkeypatch.setattr(wan_client.urllib.request, "urlopen", lambda *a, **k: pytest.fail("network"))
    assert cli(["make it snow", "--edit", "clips/street.mp4", "--tier", "480p", "--silent", "--dry-run"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["reference_videos"] == [{"url": "https://upload.invalid/street.mp4"}]
    assert body["omni_reference_task_type"] == "edit" and body["generate_audio"] is False
