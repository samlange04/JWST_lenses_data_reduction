#!/usr/bin/env bash
# Cut stamps for every mosaic that exists: run_cutouts_all.sh [SAMPLE] [SIZE_ARCSEC] [--variant V]
# Globs data/mosaics[_V]/<sample>/*/F*/ (a stamp needs a mosaic), like the HST runner.
SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; WS="$(dirname "$SD")"
LOG="$WS/data/run_logs"; mkdir -p "$LOG"
VARIANT=""; ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in --variant) VARIANT="$2"; shift 2;; *) ARGS+=("$1"); shift;; esac
done
set -- ${ARGS[@]+"${ARGS[@]}"}
SAMPLE="$(uv run --project "$WS" python "$SD/lens_samples.py" ${1:+"$1"} --print-sample)" || exit 1
SIZE="${2:-12}"
MROOT="mosaics${VARIANT:+_$VARIANT}"
ok=0; fail=0
for d in "$WS"/data/"$MROOT"/"$SAMPLE"/*/F*; do
  [ -d "$d" ] || continue
  ls "$d"/*_i2d.fits >/dev/null 2>&1 || continue
  lens=$(basename "$(dirname "$d")"); filt=$(basename "$d")
  if uv run --project "$WS" python "$SD/make_cutouts.py" --lens "$lens" --filt "$filt" --sample "$SAMPLE" \
       --size "$SIZE" ${VARIANT:+--variant "$VARIANT"} > "$LOG/${lens}_${filt}_cut.log" 2>&1; then
    ok=$((ok+1))
  else
    fail=$((fail+1)); echo "FAILED: $lens $filt (see $LOG/${lens}_${filt}_cut.log)"
  fi
done
echo "=== cutouts $SAMPLE ${SIZE}\" done: $ok ok, $fail failed ==="
