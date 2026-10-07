"""python -m wan3 "prompt" [options]  -- one Wan 3.0 video from the command line.

Local paths given to --first/--last/--image/--video/--audio/--edit are uploaded first.
"""
from __future__ import annotations

import argparse
import json
import sys

from .client import RATIOS, TIERS, Shot, Wan3, Wan3Error, price


def _is_local(value: str) -> bool:
    return not value.startswith("https://")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m wan3", description=__doc__)
    ap.add_argument("prompt")
    ap.add_argument("--seconds", type=int, help="2-30 (default 5); not used with --edit")
    ap.add_argument("--tier", default="720p", choices=TIERS)
    ap.add_argument("--ratio", choices=RATIOS)
    ap.add_argument("--first", help="first frame (image)")
    ap.add_argument("--last", help="last frame (needs --first)")
    ap.add_argument("--image", action="append", default=[], help="reference image, repeatable")
    ap.add_argument("--video", action="append", default=[], help="reference clip 1-15 s, repeatable")
    ap.add_argument("--audio", action="append", default=[], help="reference audio 1-15 s, repeatable")
    ap.add_argument("--edit", help="clip to rewrite (1-15 s); keeps its length and ratio")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--silent", action="store_true", help="generate_audio: false")
    ap.add_argument("--out", default="wan3.mp4")
    ap.add_argument("--dry-run", action="store_true", help="print the request body and price, send nothing")
    a = ap.parse_args(argv)

    videos = ([a.edit] if a.edit else []) + a.video
    shot = Shot(a.prompt, duration=a.seconds, resolution=a.tier, aspect_ratio=a.ratio,
                start_image=a.first, end_image=a.last, images=a.image, videos=videos, audios=a.audio,
                edit=bool(a.edit), seed=a.seed, sound=not a.silent)
    try:
        if a.dry_run:
            stand_in = lambda v: v if v is None or not _is_local(v) else "https://upload.invalid/" + v.split("/")[-1]
            preview = Shot(**{**shot.__dict__, "start_image": stand_in(shot.start_image),
                              "end_image": stand_in(shot.end_image),
                              "images": [stand_in(v) for v in shot.images],
                              "videos": [stand_in(v) for v in shot.videos],
                              "audios": [stand_in(v) for v in shot.audios]})
            print(json.dumps(preview.body(), indent=2))
            if not a.edit:
                print(f"price without reference video: ${price(a.seconds or 5, a.tier):.3f}", file=sys.stderr)
            return 0
        client = Wan3()
        up = lambda v: client.upload(v) if v and _is_local(v) else v
        shot.start_image, shot.end_image = up(shot.start_image), up(shot.end_image)
        shot.images = [up(v) for v in shot.images]
        shot.videos = [up(v) for v in shot.videos]
        shot.audios = [up(v) for v in shot.audios]
        job = client.run(shot, a.out, progress=lambda j: print(f"{j.get('status')} {j.get('progress', 0)}%",
                                                                file=sys.stderr))
    except Wan3Error as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"saved": a.out, "usage": job.get("usage")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
