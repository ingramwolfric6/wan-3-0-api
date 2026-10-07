"""Audio as the only reference: on wan-3 a song or a voice line can drive the clip by itself
(wan-3-prime and MiniMax H3 need an image or video beside the audio)."""
from wan3 import Wan3

job = Wan3().reference_to_video(
    "A hand-drawn ink animation of a city skyline that pulses and redraws itself to the rhythm of @Audio 1",
    "skyline-beat.mp4",
    audios=["https://example.com/beat-10s.mp3"],
    duration=10,
    resolution="480p",
    aspect_ratio="1:1",
)
print(job["usage"])  # audio is free: 10 billed seconds x $0.038 = $0.38
