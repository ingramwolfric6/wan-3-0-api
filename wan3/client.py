"""Wan 3.0 (`wan-3`) client on the async /v1/videos protocol, standard library only.

Five ways in, one endpoint: text, first frame, first + last frame, references
(images, video and/or audio) and editing an existing clip. The helpers below
build each request body, check it against the published limits and run the
submit -> poll -> download cycle.
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

MODEL = "wan-3"
BASE_URL = "https://argolink.io/v1"
USER_AGENT = "wan-3-0-api/1.0"              # sent on every request, including upload PUTs

TIERS = ("480p", "720p", "1080p")
RATIOS = ("21:9", "16:9", "4:3", "1:1", "3:4", "9:16", "adaptive")
SECONDS = range(2, 31)                       # 2-30 s, whole seconds
PROMPT_LIMIT = 20_000
SEED_MAX = 4_294_967_295
LIMITS = {"images": 10, "videos": 5, "audios": 5, "total": 20}

# ArgoLink price per billed second, from https://argolink.io/en/models/wan-3 on 2026-10-07.
RATE = {"480p": 0.038, "720p": 0.075, "1080p": 0.15}

MEDIA_TYPES = {
    "jpg": ("image", "image/jpeg"), "jpeg": ("image", "image/jpeg"), "png": ("image", "image/png"),
    "mp4": ("video", "video/mp4"), "mov": ("video", "video/quicktime"),
    "mp3": ("audio", "audio/mpeg"), "wav": ("audio", "audio/wav"),
}


class Wan3Error(Exception):
    """Validation failure, HTTP error (see .http_status/.body) or a job that did not finish."""

    def __init__(self, message: str, http_status: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.http_status = http_status
        self.body = body


def price(seconds: int, tier: str = "720p", reference_video_seconds: float = 0) -> float:
    """What a finished job costs: (output s + whole reference-video s) x tier rate.
    An edit counts the edited clip twice: once as output, once as reference."""
    if tier not in RATE:
        raise Wan3Error(f"unknown tier {tier!r}; use one of {TIERS}")
    return round((seconds + math.floor(reference_video_seconds)) * RATE[tier], 4)


@dataclass
class Shot:
    """One request. Leave fields at their defaults to let the API apply its own."""

    prompt: str
    duration: Optional[int] = None         # None -> 5 s (the API default); must stay None for an edit
    resolution: str = "720p"
    aspect_ratio: Optional[str] = None
    start_image: Optional[str] = None
    end_image: Optional[str] = None
    images: Sequence[str] = field(default_factory=list)
    videos: Sequence[str] = field(default_factory=list)
    audios: Sequence[str] = field(default_factory=list)
    edit: bool = False                      # edit videos[0]; it keeps its own length and ratio
    seed: Optional[int] = None
    sound: bool = True                      # False -> generate_audio: false, a silent MP4

    def body(self) -> Dict[str, Any]:
        """The JSON for POST /videos/generations; raises Wan3Error on anything the API would refuse."""
        if not self.prompt or not self.prompt.strip():
            raise Wan3Error("prompt is required in every mode")
        if len(self.prompt) > PROMPT_LIMIT:
            raise Wan3Error(f"prompt is {len(self.prompt)} characters; the limit is {PROMPT_LIMIT}")
        if self.resolution not in TIERS:
            raise Wan3Error(f"resolution must be one of {', '.join(TIERS)}")
        if self.aspect_ratio is not None and self.aspect_ratio not in RATIOS:
            raise Wan3Error(f"aspect_ratio must be one of {', '.join(RATIOS)}")
        if self.seed is not None and (isinstance(self.seed, bool) or not isinstance(self.seed, int)
                                      or not 0 <= self.seed <= SEED_MAX):
            raise Wan3Error(f"seed must be an integer from 0 to {SEED_MAX}")
        frames = self.start_image is not None or self.end_image is not None
        refs = len(self.images) + len(self.videos) + len(self.audios)

        out: Dict[str, Any] = {"model": MODEL, "prompt": self.prompt, "resolution": self.resolution}
        if self.edit:
            if frames:
                raise Wan3Error("an edit cannot take start_image or end_image")
            if not self.videos:
                raise Wan3Error("an edit needs the clip to edit as videos[0]")
            if self.duration is not None or self.aspect_ratio is not None:
                raise Wan3Error("an edit keeps the source clip's length and ratio: leave duration and aspect_ratio unset")
            out["omni_reference_task_type"] = "edit"
        else:
            seconds = 5 if self.duration is None else self.duration
            if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds not in SECONDS:
                raise Wan3Error("duration must be a whole number of seconds from 2 to 30")
            out["duration"] = seconds
            if frames:
                if self.start_image is None:
                    raise Wan3Error("end_image needs start_image")
                if refs:
                    raise Wan3Error("first/last frames cannot be mixed with reference assets")
                out["aspect_ratio"] = self.aspect_ratio or "adaptive"   # a fixed ratio crops the frame
                out["start_image"] = {"url": _https(self.start_image)}
                if self.end_image is not None:
                    out["end_image"] = {"url": _https(self.end_image)}
            else:
                out["aspect_ratio"] = self.aspect_ratio or "16:9"

        if len(self.images) > LIMITS["images"] or len(self.videos) > LIMITS["videos"] or len(self.audios) > LIMITS["audios"]:
            raise Wan3Error("reference limits: 10 images, 5 videos, 5 audio clips")
        if refs > LIMITS["total"]:
            raise Wan3Error("reference limits: 20 assets in total")
        for key, urls in (("reference_images", self.images), ("reference_videos", self.videos),
                          ("reference_audios", self.audios)):
            if urls:
                out[key] = [{"url": _https(u)} for u in urls]
        if self.seed is not None:
            out["seed"] = self.seed
        if not self.sound:
            out["generate_audio"] = False
        return out


def _https(url: str) -> str:
    if not isinstance(url, str) or not url.startswith("https://"):
        raise Wan3Error(f"{url!r} is not an https:// URL; upload local files with Wan3.upload() first")
    return url


class Wan3:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None,
                 timeout: float = 60, poll_seconds: float = 10):
        self.api_key = api_key or os.environ.get("WAN_API_KEY", "")
        if not self.api_key:
            raise Wan3Error("no API key: set WAN_API_KEY")
        self.base_url = (base_url or os.environ.get("WAN_BASE_URL") or BASE_URL).rstrip("/")
        self.timeout = timeout
        self.poll_seconds = poll_seconds

    def _http(self, method: str, path: str, payload: Optional[dict] = None, binary: bool = False) -> Any:
        req = urllib.request.Request(
            self.base_url + path,
            data=None if payload is None else json.dumps(payload).encode(),
            method=method,
            headers={"Authorization": f"Bearer {self.api_key}", "User-Agent": USER_AGENT,
                     **({"Content-Type": "application/json"} if payload is not None else {})},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", "replace")
            try:
                body: Any = json.loads(text)
            except ValueError:
                body = text
            detail = body.get("error", body) if isinstance(body, dict) else body
            raise Wan3Error(f"{method} {path}: HTTP {exc.code}: {detail}", exc.code, body) from None
        except urllib.error.URLError as exc:
            raise Wan3Error(f"{method} {path}: {exc.reason}") from None
        return raw if binary else json.loads(raw)

    # -- one call per protocol step ---------------------------------------------------

    def submit(self, shot: Shot) -> str:
        reply = self._http("POST", "/videos/generations", shot.body())
        return reply["request_id"]

    def status(self, request_id: str) -> Dict[str, Any]:
        return self._http("GET", f"/videos/{request_id}")

    def wait(self, request_id: str, timeout: float = 3600,
             progress: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
        stop_at = time.monotonic() + timeout
        while True:
            job = self.status(request_id)
            if job.get("status") == "done":
                return job
            if job.get("status") in ("failed", "expired"):
                raise Wan3Error(f"{request_id} ended {job['status']}: {job.get('error')}", body=job)
            if progress:
                progress(job)
            if time.monotonic() > stop_at:
                raise Wan3Error(f"{request_id} still {job.get('status')}; keep the id and poll later", body=job)
            time.sleep(self.poll_seconds)

    def save(self, request_id: str, path: str) -> str:
        data = self._http("GET", f"/videos/{request_id}/content", binary=True)
        tmp = path + ".part"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
        return path

    def upload(self, path: str) -> str:
        """Local JPEG/PNG/MP4/MOV/MP3/WAV -> media_url (valid for seven days). Tickets are free."""
        ext = path.rsplit(".", 1)[-1].lower()
        if ext not in MEDIA_TYPES:
            raise Wan3Error(f"cannot upload .{ext}; use JPEG, PNG, MP4, MOV, MP3 or WAV")
        kind, ctype = MEDIA_TYPES[ext]
        ticket = self._http("POST", "/media/uploads", {"model": MODEL, "type": kind, "content_type": ctype,
                                                         "size_bytes": os.path.getsize(path)})
        with open(path, "rb") as fh:
            put = urllib.request.Request(ticket["upload_url"], data=fh.read(), method="PUT",
                                         headers={"Content-Type": ctype, "User-Agent": USER_AGENT})
        urllib.request.urlopen(put, timeout=self.timeout).close()
        return ticket["media_url"]

    # -- conveniences -------------------------------------------------------------------

    def run(self, shot: Shot, path: str, progress: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
        """Submit, wait, save. Returns the finished job (its usage holds the billed seconds)."""
        request_id = self.submit(shot)
        job = self.wait(request_id, progress=progress)
        self.save(request_id, path)
        return job

    def text_to_video(self, prompt: str, path: str, **kw: Any) -> Dict[str, Any]:
        return self.run(Shot(prompt, **kw), path)

    def image_to_video(self, prompt: str, start_image: str, path: str, end_image: Optional[str] = None,
                       **kw: Any) -> Dict[str, Any]:
        return self.run(Shot(prompt, start_image=start_image, end_image=end_image, **kw), path)

    def reference_to_video(self, prompt: str, path: str, images: Sequence[str] = (), videos: Sequence[str] = (),
                           audios: Sequence[str] = (), **kw: Any) -> Dict[str, Any]:
        return self.run(Shot(prompt, images=list(images), videos=list(videos), audios=list(audios), **kw), path)

    def edit_video(self, prompt: str, video: str, path: str, extra_videos: Sequence[str] = (),
                   images: Sequence[str] = (), audios: Sequence[str] = (), **kw: Any) -> Dict[str, Any]:
        """Rewrite an existing 1-15 s clip; @Video 1 is that clip. Bills its length twice."""
        if len(extra_videos) > LIMITS["videos"] - 1:
            raise Wan3Error("an edit takes the edited clip plus at most 4 more videos")
        shot = Shot(prompt, edit=True, videos=[video, *extra_videos],
                    images=list(images), audios=list(audios), **kw)
        return self.run(shot, path)


def models_from(listing: Dict[str, Any]) -> List[str]:
    """IDs from a GET /v1/models reply (handy to confirm wan-3 and wan-3-prime are listed)."""
    return [item["id"] for item in listing.get("data", [])]
