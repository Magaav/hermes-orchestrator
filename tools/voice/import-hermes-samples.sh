#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dataset="${HERMES_WAKE_DATASET:-$repo_root/data/voice/hermes}"
kind=""
source_dir=""
speaker="${HERMES_WAKE_SPEAKER:-import}"
device_label="${HERMES_WAKE_DEVICE_LABEL:-unknown-device}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --positive)
      kind="positive"
      shift
      ;;
    --negative-silence)
      kind="negative/silence"
      shift
      ;;
    --negative-speech)
      kind="negative/speech"
      shift
      ;;
    --negative-noise)
      kind="negative/noise"
      shift
      ;;
    --from)
      source_dir="${2:-}"
      shift 2
      ;;
    --speaker)
      speaker="${2:-}"
      shift 2
      ;;
    --device-label)
      device_label="${2:-}"
      shift 2
      ;;
    *)
      echo "Usage: $0 (--positive|--negative-silence|--negative-speech|--negative-noise) --from wav_dir [--speaker id] [--device-label id]" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$kind" || -z "$source_dir" ]]; then
  echo "Missing sample kind or --from wav_dir" >&2
  exit 2
fi
if [[ ! -d "$source_dir" ]]; then
  echo "Source directory not found: $source_dir" >&2
  exit 1
fi

target="$dataset/$kind"
mkdir -p "$target"
count=0
skipped=0
converted=0

is_contract_wav() {
  python3 - "$1" <<'PY'
import sys
import wave
from pathlib import Path

path = Path(sys.argv[1])
if path.stat().st_size == 0:
    raise SystemExit(1)
try:
    with wave.open(str(path), "rb") as wav:
        ok = wav.getnchannels() == 1 and wav.getframerate() == 16000 and wav.getsampwidth() == 2 and wav.getnframes() > 0
except wave.Error:
    ok = False
raise SystemExit(0 if ok else 1)
PY
}

safe_name() {
  local source="$1"
  local stem
  local stamp
  local candidate
  local n
  stem="$(basename "$source")"
  stem="${stem%.*}"
  stem="$(printf '%s' "$stem" | tr -cs 'A-Za-z0-9._-' '_')"
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  candidate="$target/${kind//\//-}_${speaker}_${device_label}_${stamp}_${stem}.wav"
  n=1
  while [[ -e "$candidate" ]]; do
    candidate="$target/${kind//\//-}_${speaker}_${device_label}_${stamp}_${stem}_$n.wav"
    n=$((n + 1))
  done
  printf '%s\n' "$candidate"
}

while IFS= read -r -d '' wav; do
  if [[ ! -s "$wav" ]]; then
    echo "Skipping zero-byte placeholder: $wav" >&2
    skipped=$((skipped + 1))
    continue
  fi
  dest="$(safe_name "$wav")"
  if is_contract_wav "$wav"; then
    cp "$wav" "$dest"
  elif command -v ffmpeg >/dev/null 2>&1; then
    ffmpeg -hide_banner -loglevel error -y -i "$wav" -ac 1 -ar 16000 -sample_fmt s16 "$dest"
    converted=$((converted + 1))
  else
    echo "Skipping non-16k-mono-PCM16 WAV without ffmpeg for conversion: $wav" >&2
    skipped=$((skipped + 1))
    continue
  fi
  if [[ ! -s "$dest" ]]; then
    echo "Converted/imported file is empty, removing: $dest" >&2
    rm -f "$dest"
    skipped=$((skipped + 1))
    continue
  fi
  echo "$dest"
  count=$((count + 1))
done < <(find "$source_dir" -maxdepth 1 -type f -iname '*.wav' -print0)

echo "Imported $count WAV sample(s) into $target ($converted converted, $skipped skipped)"
