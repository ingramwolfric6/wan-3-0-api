"""First + last frame: Wan 3.0 animates between two stills.

aspect_ratio "adaptive" follows the first frame; a fixed ratio such as "9:16" crops it instead.
"""
from wan3 import Shot, Wan3, price

shot = Shot(
    "The empty stage fills with dancers as the lights come up, camera slowly dollying in",
    duration=6,
    resolution="1080p",
    start_image="https://example.com/stage-empty.png",
    end_image="https://example.com/stage-full.png",
)
print(f"${price(6, '1080p'):.2f}")  # 6 x $0.15 = $0.90
job = Wan3().run(shot, "stage.mp4")
print(job["usage"])
