"""Wan 3.0 as MCP tools over stdio (MCP Python SDK 2.x, Python 3.10+).

    pip install -e ".[mcp]"
    WAN_API_KEY=... wan3-mcp        # or: python -m wan3.mcp_server
"""
from typing import Any, Dict, List, Optional

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .client import Shot, Wan3, Wan3Error, price

server = MCPServer(
    "wan-3",
    instructions=(
        "Alibaba Wan 3.0 video. create_video covers text, first frame, first+last frame and references; "
        "edit_video rewrites an existing 1-15 s clip. Both return a request_id immediately: poll "
        "check_video every 10-15 s until done, failed or expired, then fetch_video. Do not resubmit a job "
        "that already has a request_id. 2-30 s; 480p, 720p or 1080p; seed and silent output are supported."
    ),
)


def _submit(shot: Shot, seconds_for_price: Optional[int], tier: str) -> Dict[str, Any]:
    try:
        request_id = Wan3().submit(shot)
    except Wan3Error as exc:
        raise ToolError(str(exc)) from exc
    answer: Dict[str, Any] = {"request_id": request_id}
    if seconds_for_price:
        answer["price_usd_before_reference_video"] = price(seconds_for_price, tier)
    return answer


@server.tool()
def create_video(
    prompt: str,
    seconds: int = 5,
    tier: str = "720p",
    aspect_ratio: Optional[str] = None,
    start_image: Optional[str] = None,
    end_image: Optional[str] = None,
    images: Optional[List[str]] = None,
    videos: Optional[List[str]] = None,
    audios: Optional[List[str]] = None,
    seed: Optional[int] = None,
    silent: bool = False,
) -> Dict[str, Any]:
    """Start a Wan 3.0 job. Frames (start_image, end_image) and references (images <=10, videos <=5,
    audios <=5, 20 total) are HTTPS URLs and cannot be mixed. aspect_ratio: 21:9, 16:9, 4:3, 1:1, 3:4,
    9:16 or adaptive. Reference video seconds are billed like output seconds."""
    shot = Shot(prompt, duration=seconds, resolution=tier, aspect_ratio=aspect_ratio, start_image=start_image,
                end_image=end_image, images=images or [], videos=videos or [], audios=audios or [],
                seed=seed, sound=not silent)
    return _submit(shot, seconds, tier)


@server.tool()
def edit_video(
    prompt: str,
    video: str,
    tier: str = "720p",
    images: Optional[List[str]] = None,
    extra_videos: Optional[List[str]] = None,
    audios: Optional[List[str]] = None,
    seed: Optional[int] = None,
    silent: bool = False,
) -> Dict[str, Any]:
    """Rewrite an existing HTTPS clip (1-15 s) as the prompt says; the result keeps its length and ratio.
    @Video 1 is that clip. The edited clip is billed twice: as output and as reference."""
    shot = Shot(prompt, resolution=tier, edit=True, videos=[video, *(extra_videos or [])],
                images=images or [], audios=audios or [], seed=seed, sound=not silent)
    return _submit(shot, None, tier)


@server.tool()
def check_video(request_id: str) -> Dict[str, Any]:
    """Status once: pending (progress 0-99), done (video.url, usage), failed or expired (error)."""
    try:
        return Wan3().status(request_id)
    except Wan3Error as exc:
        raise ToolError(str(exc)) from exc


@server.tool()
def fetch_video(request_id: str, path: str) -> Dict[str, Any]:
    """Download a done job's MP4 to a local path."""
    try:
        return {"saved": Wan3().save(request_id, path)}
    except Wan3Error as exc:
        raise ToolError(str(exc)) from exc


def main() -> None:
    server.run()  # stdio


if __name__ == "__main__":
    main()
