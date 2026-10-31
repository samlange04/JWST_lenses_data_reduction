#!/usr/bin/env bash
# psf_star_check.py on every band with a mosaic, JOBS at a time (default 4):
#   run_psf_star_check_all.sh [JOBS] [SAMPLE ...]      (default: every sample)
# Per-band logs in data/run_logs/<lens>_<FILT>_starcheck.log. Then, by hand:
#   uv run python scripts/psf_star_check.py --calibrate     (pass 1, STPSF's default widths)
#   ... re-run this (pass 2, the calibrated widths), then --error-maps.
# Wait on this PROCESS (AGENTS.md, *Long batch runs*); it ends with a "=== ... done" line.
SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; WS="$(dirname "$SD")"
LOG="$WS/data/run_logs"; mkdir -p "$LOG"
JOBS="${1:-4}"; shift $(( $# > 0 ? 1 : 0 ))
SAMPLES="$*"
[ -n "$SAMPLES" ] || SAMPLES="$(cd "$WS" && uv run python -c 'import sys; sys.path.insert(0, "scripts"); import lens_samples; print(" ".join(lens_samples.samples()))')"
one() {
  if uv run --project "$WS" python "$SD/psf_star_check.py" --sample "$1" --lens "$2" --filt "$3" > "$LOG/${2}_${3}_starcheck.log" 2>&1; then
    echo "ok $2 $3 $(tail -1 "$LOG/${2}_${3}_starcheck.log")"
  else
    echo "FAILED $2 $3 (see $LOG/${2}_${3}_starcheck.log)"
  fi
}
export -f one; export SD WS LOG
for s in $SAMPLES; do
  for d in "$WS"/data/mosaics/"$s"/*/F*; do
    ls "$d"/*_i2d.fits >/dev/null 2>&1 && echo "$s $(basename "$(dirname "$d")") $(basename "$d")"
  done
done | xargs -P "$JOBS" -n 3 bash -c 'one "$0" "$1" "$2"'
echo "=== psf star check done $(date +%H:%M:%S) ==="
