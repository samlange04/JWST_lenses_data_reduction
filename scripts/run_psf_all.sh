#!/usr/bin/env bash
# PSFs for every mosaic that exists: run_psf_all.sh [SAMPLE] [extra make_psf.py args...]
SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; WS="$(dirname "$SD")"
LOG="$WS/data/run_logs"; mkdir -p "$LOG"
SAMPLE="$(uv run --project "$WS" python "$SD/lens_samples.py" ${1:+"$1"} --print-sample)" || exit 1
shift $(( $# > 0 ? 1 : 0 ))
ok=0; fail=0
for d in "$WS"/data/mosaics/"$SAMPLE"/*/F*; do
  [ -d "$d" ] || continue
  ls "$d"/*_i2d.fits >/dev/null 2>&1 || continue
  lens=$(basename "$(dirname "$d")"); filt=$(basename "$d")
  if uv run --project "$WS" python "$SD/make_psf.py" --lens "$lens" --filt "$filt" --sample "$SAMPLE" "$@" \
       > "$LOG/${lens}_${filt}_psf.log" 2>&1; then ok=$((ok+1))
  else fail=$((fail+1)); echo "FAILED: $lens $filt (see $LOG/${lens}_${filt}_psf.log)"; fi
done
echo "=== psf $SAMPLE done: $ok ok, $fail failed ==="
