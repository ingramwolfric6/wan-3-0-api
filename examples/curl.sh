#!/usr/bin/env bash
# The three calls by hand: submit, poll, download.
set -euo pipefail
: "${WAN_API_KEY:?export WAN_API_KEY}"
BASE="${WAN_BASE_URL:-https://argolink.io/v1}"
H="Authorization: Bearer $WAN_API_KEY"

ID=$(curl -fsS "$BASE/videos/generations" -H "$H" -H "Content-Type: application/json" -d '{
  "model": "wan-3",
  "prompt": "Morning fog lifts off a mountain lake while a lone canoe glides across, wide shot",
  "duration": 12, "resolution": "720p", "aspect_ratio": "21:9", "seed": 7
}' | jq -er .request_id)

until JOB=$(curl -fsS "$BASE/videos/$ID" -H "$H"); S=$(jq -r .status <<<"$JOB"); [ "$S" != pending ]; do
  echo "pending $(jq -r '.progress // 0' <<<"$JOB")%" >&2; sleep 10
done
[ "$S" = done ] || { jq '{status, error}' <<<"$JOB" >&2; exit 1; }
curl -fsSL "$BASE/videos/$ID/content" -H "$H" -o lake.mp4 && jq .usage <<<"$JOB"
