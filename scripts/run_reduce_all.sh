#!/usr/bin/env bash
# Download (if needed) and reduce every lens of a sample in every NIRCam filter it has.
#
# Usage: run_reduce_all.sh [SAMPLE] [extra reduce_nircam.py args...]
#          (default SAMPLE: lens_samples.DEFAULT_SAMPLE)
#
# Iterates the sample ROSTER (info/samples/lens_samples.json), not a glob: a lens whose pool is
# empty is downloaded first. Filters come from the lens's sorted pool
# (data/calibrated/<sample>/<lens>/F*/), so only bands MAST actually has are tried.
# Per-band logs in data/run_logs/<lens>_<FILT>_reduce.log; exit status is counted as
# ok / no data / FAILED. Detector1 on B1938+666 is many hours: run this in the background
# and wait on the PROCESS, never on a file-timestamp poll (AGENTS.md, *Long batch runs*).
SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; WS="$(dirname "$SD")"
LOG="$WS/data/run_logs"; mkdir -p "$LOG"
SAMPLE="$(uv run --project "$WS" python "$SD/lens_samples.py" ${1:+"$1"} --print-sample)" || exit 1
shift $(( $# > 0 ? 1 : 0 ))
ok=0; nodata=0; fail=0
for lens in $(uv run --project "$WS" python "$SD/lens_samples.py" "$SAMPLE"); do
  pool="$WS/data/calibrated/$SAMPLE/$lens/pool"
  if ! ls "$pool"/*_uncal.fits >/dev/null 2>&1; then
    echo "--- $lens: downloading"
    uv run --project "$WS" python "$SD/download_nircam.py" --lens "$lens" --sample "$SAMPLE" \
      > "$LOG/${lens}_download.log" 2>&1 || { echo "FAILED download: $lens"; fail=$((fail+1)); continue; }
  fi
  for d in "$WS"/data/calibrated/"$SAMPLE"/"$lens"/F*; do
    [ -d "$d" ] || continue
    filt=$(basename "$d")
    echo "--- $lens $filt  $(date +%H:%M:%S)"
    if uv run --project "$WS" python "$SD/reduce_nircam.py" --lens "$lens" --filt "$filt" --sample "$SAMPLE" "$@" \
         > "$LOG/${lens}_${filt}_reduce.log" 2>&1; then
      if grep -q "=== NO DATA" "$LOG/${lens}_${filt}_reduce.log"; then nodata=$((nodata+1)); else ok=$((ok+1)); fi
    else
      fail=$((fail+1)); echo "FAILED: $lens $filt (see $LOG/${lens}_${filt}_reduce.log)"
    fi
  done
done
echo "=== reduce $SAMPLE done: $ok ok, $nodata no data, $fail failed  $(date +%H:%M:%S) ==="
