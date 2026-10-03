"""Verify saved real-browser keyboard evidence, not a substitute for browser operation."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1] / 'output/decision_v2/ui'
cycles = []
for size in ('medium', 'mobile', 'desktop'):
    for theme in ('dark', 'light'):
        for mode in ('offense', 'defense'):
            name = f'{size}-{theme}-replay-{mode}-fixed'
            rows = json.loads((root / f'keyboard-{name}.json').read_text(encoding='utf8'))
            assert len(rows) == 180, name
            assert any(x['tag'] == 'BODY' for x in rows), (name, 'cycle did not return')
            for x in rows:
                if x['tag'] == 'BODY':
                    continue
                assert x['outline'] != 'none', (name, x)
                if not x['headerControl'] and not x['skip']:
                    assert x['top'] >= x['headerBottom'], (name, x)
            cycles.append(name)

for theme in ('dark', 'light'):
    for mode in ('offense', 'defense'):
        name = f'medium-{theme}-custom-{mode}-fixed'
        rows = json.loads((root / f'keyboard-{name}.json').read_text(encoding='utf8'))
        assert len(rows) == 180 and any(x['tag'] == 'BODY' for x in rows), name
        for x in rows:
            if x['tag'] == 'BODY':
                continue
            assert x['outline'] != 'none', (name, x)
            if not x['headerControl'] and not x['skip']:
                assert x['top'] >= x['headerBottom'], (name, x)
        cycles.append(name)

cases = json.loads((root / 'tablet-focus-regression.json').read_text(encoding='utf8'))
assert len(cases) == 48
for x in cases:
    assert x['focusTag'] == 'DIV' and x['focusTop'] >= x['headerBottom'], x
    assert not x['overflow'], x
    assert x['style'] == 'style.css?v=20261003-v3'
    assert x['app'] == 'app.js?v=20261003-v7'
for width in (390, 602, 640, 768, 1000, 1440):
    for mode in ('offense', 'defense'):
        for direction in ('forward', 'backward'):
            pair = [x for x in cases if x['width'] == width and x['mode'] == mode and x['direction'] == direction]
            assert len(pair) == 2 and {x['theme'] for x in pair} == {'dark', 'light'}
            assert pair[0]['table'] == pair[1]['table'], (width, mode, direction)

summary = dict(replay_focus_cycles=12, custom_focus_cycles=4, total_focus_cycles=len(cycles),
               focus_cases=len(cases), identical_theme_pairs=24,
               viewport_simulation=True, physical_devices_verified=False,
               browser_zoom_verified=False, screen_reader_verified=False)
(root / 'keyboard-verification.json').write_text(json.dumps(summary, indent=2), encoding='utf8')
print(json.dumps(summary, indent=2))
