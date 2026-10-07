"""Edit an existing clip (1-15 s). The result keeps the clip's length and ratio; leave duration
and aspect_ratio out. The edited clip is billed as output and as reference: a 6 s edit bills 12 s."""
from wan3 import Wan3, price

client = Wan3()
source = client.upload("street-6s.mp4")  # local file -> media_url (or pass an https URL directly)
job = client.edit_video(
    "Turn the daytime street into a rainy night with neon reflections; keep the people and camera move",
    source,
    "street-night.mp4",
    resolution="720p",
)
print(job["usage"], f"expected ${price(6, '720p', reference_video_seconds=6):.2f}")  # $0.90
