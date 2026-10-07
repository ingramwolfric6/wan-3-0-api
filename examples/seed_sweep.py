"""Same prompt, three seeds: render cheap 480p drafts, then re-render the winner's seed at 1080p.
A seed repeats a render only when the rest of the request is identical, so keep the prompt fixed."""
from wan3 import Shot, Wan3, price

PROMPT = "A glass of iced tea sweating on a wooden table, slow rack focus to a garden behind it"
client = Wan3()
for seed in (11, 22, 33):
    client.run(Shot(PROMPT, duration=4, resolution="480p", seed=seed), f"tea-{seed}.mp4")
print(f"three drafts: ${3 * price(4, '480p'):.3f}")  # 3 x 4 x $0.038 = $0.456
