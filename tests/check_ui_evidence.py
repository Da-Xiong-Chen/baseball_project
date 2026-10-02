"""核對實際瀏覽器保存的 DOM 與色彩證據；不代替重新操作瀏覽器。"""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1] / 'output/decision_v2/ui'
palette = json.loads((root / 'palette.json').read_text(encoding='utf8'))

def luminance(color):
    values = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    return sum(w * (v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4)
               for w, v in zip((.2126, .7152, .0722), values))

contrasts = []
for theme in palette:
    for foreground, background in [('--text','--panel'), ('--muted','--panel'),
                                   ('--muted','--panel-2'), ('--accent','--accent-soft'),
                                   ('--pos','--panel'), ('--neg','--panel'), ('--warn','--warn-soft')]:
        low, high = sorted((luminance(theme[foreground]), luminance(theme[background])))
        ratio = (high + .05) / (low + .05)
        assert ratio >= 4.5, (theme['theme'], foreground, background, ratio)
        contrasts.append(dict(theme=theme['theme'], foreground=foreground,
                              background=background, ratio=round(ratio, 2)))
(root / 'contrast.json').write_text(json.dumps(contrasts, indent=2), encoding='utf8')
cases = json.loads((root / 'ui-evidence.json').read_text(encoding='utf8'))
assert len(cases) == 8
assert all(c['scroll'] <= c['viewport'] and not c['errors'] for c in cases)
assert all(c['comparisonCount'] == 2 for c in cases)
assert all(float(c['scrollPadding'].removesuffix('px')) > c['headerHeight'] for c in cases)
for width in (1440, 390):
    for mode in ('offense', 'defense'):
        pair = [c for c in cases if c['width'] == width and c['mode'] == mode]
        assert len(pair) == 2 and pair[0]['table'] == pair[1]['table'], (width, mode)
print('8 UI cases; 4 identical theme pairs; 14 palette contrasts pass. Minimum:', min(c['ratio'] for c in contrasts))
