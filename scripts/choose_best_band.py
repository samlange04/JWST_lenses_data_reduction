#!/usr/bin/env python
"""
Choose each lens's best (primary) band BY EYE: a GUI over the lens's band overview.

    uv run python scripts/choose_best_band.py --sample cowls_spectacular             # every lens
    uv run python scripts/choose_best_band.py --sample cowls_spectacular --unreviewed
    uv run python scripts/choose_best_band.py --sample spt --lens SPT2147-50

The primary band is the one where the lensed images are best defined: the mask GUIs draw it
first, positions are clicked on it, and it is the band to model first. choose_primary_band.py
measures a suggestion (arc S/N discounted for coarse resolution), but the measurement is only
a guide. It missed B1938+666 (F115W's 0.03" pixels beat F277W's S/N on a 0.45" ring) and
COSJ100018+022138 (F150W), and had nothing to say on two lenses with faint arcs. This makes the
choice the reviewer's.

For each lens it opens the band overview (make_band_overview.build_figure: every band, full
stamp, zoom, isophote-subtracted zoom), with each band's measured arc S/N and score under its
name and the current choice outlined.
  * click a band's column, or press 1-N (bands in wavelength order), to select it;
  * Enter accepts the selection: it is written to info/samples/lens_samples.json as the
    lens's reviewed `primary_band`, with a note naming this script and the measured
    suggestion, then the records and the overview PNG are refreshed
    (choose_primary_band.record);
  * s (or closing the window) skips the lens, leaving it as it was; q quits.
--unreviewed shows only lenses without a reviewed band.
"""
import argparse
import datetime
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import choose_primary_band
import lens_samples
import make_band_overview

ws_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PICK = '#d62728'


def choose(sample, lens):
    """Show the lens and return ('pick', band), ('skip', None) or ('quit', None)."""
    import matplotlib.pyplot as plt
    meas = choose_primary_band.measure(sample, lens)
    current, source = lens_samples.primary_band(lens, sample)
    fig = plt.figure()
    fig, info = make_band_overview.build_figure(sample, lens, fig=fig)
    if fig is None:
        plt.close('all')
        return 'skip', None
    filts, axes = info['filts'], info['axes']
    state = dict(sel=current if current in filts else (meas['suggested'] or filts[-1]), action='skip')

    for j, f in enumerate(filts):
        sc = meas['scores'].get(f) or {}
        tag = ''
        if f == meas['suggested']:
            tag = '  [measured best]'
        axes[0][j].set_title(f'{j + 1}: {axes[0][j].get_title()}\narc S/N {sc.get("arc_snr")}  score {sc.get("score")}{tag}',
                             fontsize=9)

    def paint():
        for j, f in enumerate(filts):
            on = f == state['sel']
            for i in range(3):
                for sp in axes[i][j].spines.values():
                    sp.set_edgecolor(PICK if on else 'black')
                    sp.set_linewidth(3.5 if on else 0.8)
        fig.texts[-1].set_text(f'selected: {state["sel"]}    (current: {current or "none"}'
                               f'{f", {source}" if current else ""}; measured best: {meas["suggested"] or "none"})    '
                               f'click a column or press 1-{len(filts)}; Enter accepts, s skips, q quits')
        fig.canvas.draw_idle()

    fig.tight_layout(rect=(0, 0.04, 1, 0.90))          # room for the instruction line
    fig.text(0.5, 0.005, '', ha='center', va='bottom', fontsize=10, color=PICK, weight='bold')

    def onclick(event):
        for j in range(len(filts)):
            if any(event.inaxes is axes[i][j] for i in range(3)):
                state['sel'] = filts[j]
                paint()

    def onkey(event):
        k = event.key
        if k and k.isdigit() and 1 <= int(k) <= len(filts):
            state['sel'] = filts[int(k) - 1]
            paint()
        elif k == 'enter':
            state['action'] = 'pick'
            plt.close(fig)
        elif k == 's':
            state['action'] = 'skip'
            plt.close(fig)
        elif k == 'q':
            state['action'] = 'quit'
            plt.close(fig)

    fig.canvas.mpl_connect('button_press_event', onclick)
    fig.canvas.mpl_connect('key_press_event', onkey)
    paint()
    plt.show()
    return (state['action'], state['sel'] if state['action'] == 'pick' else None)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--sample', type=lens_samples.sample_arg, required=True)
    p.add_argument('--lens', default=None)
    p.add_argument('--unreviewed', action='store_true', help='only lenses without a reviewed primary band')
    a = p.parse_args()
    warnings.simplefilter('ignore')
    lenses = [a.lens] if a.lens else lens_samples.lenses(a.sample)
    for lens in lenses:
        current, source = lens_samples.primary_band(lens, a.sample)
        if a.unreviewed and source == 'reviewed':
            continue
        print(f'{lens}: current {current} ({source}) -- choose in the window')
        action, band = choose(a.sample, lens)
        if action == 'quit':
            print('quit')
            break
        if action == 'skip':
            print('  skipped, unchanged')
            continue
        meas = choose_primary_band.measure(a.sample, lens)
        note = (f'Chosen by eye with choose_best_band.py ({datetime.date.today().isoformat()}); '
                f'the measured best band was {meas["suggested"] or "none (arcs too faint to measure)"}.')
        lens_samples.set_primary_band(lens, band, note, a.sample)
        choose_primary_band.record(a.sample, lens)
        print(f'  primary band {band} (reviewed)')


if __name__ == '__main__':
    sys.exit(main())
