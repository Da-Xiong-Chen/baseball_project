"""PR checks using tracked exports and synthetic fixtures, never downloaded raw games."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_TESTS = ['test_runtime_config.py', 'test_training_source.py', 'test_batch_contract.py',
    'test_release_site.py', 'test_season_intake.py', 'test_incremental_intake.py', 'test_qa_boundaries.py',
    'test_repository_checks.py']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-no-raw', action='store_true')
    args = parser.parse_args()
    if args.require_no_raw and (ROOT / 'data/rebas').exists(): raise ValueError('CI verification requires a checkout without raw Rebas inputs')
    output = ROOT / 'output/ci-validation' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output.mkdir(parents=True)
    temporary = output / 'tmp'; temporary.mkdir()
    env = {k:v for k,v in os.environ.items() if not k.startswith('BASEBALL_')}
    env.update(PYTHONUTF8='1', BASEBALL_REPORT_OUT=str(output), NODE_BINARY=os.environ.get('NODE_BINARY', 'node'),
               TMPDIR=str(temporary), TMP=str(temporary), TEMP=str(temporary))
    commands = [('repository', [sys.executable, '-X', 'utf8', 'scripts/check_repository.py']),
        ('site', [sys.executable, '-X', 'utf8', 'scripts/prepare_site.py']),
        ('javascript', [env['NODE_BINARY'], '--test', *[str(p.relative_to(ROOT)) for p in sorted((ROOT/'tests').glob('test_*.cjs'))]])]
    for name in FIXTURE_TESTS:
        commands.append((name, [sys.executable, '-X', 'utf8', '-m', 'unittest', 'discover', '-s', 'tests', '-p', name]))
    legacy = [ROOT/'output/qa/engine_regression.json', ROOT/'tests/fixtures/qa_scenarios.json']
    saved = {p:p.read_bytes() if p.exists() else None for p in legacy}
    report = {'raw_data_downloaded': False, 'raw_input_required': False,
              'raw_input_directory_present': (ROOT/'data/rebas').exists(),
              'require_no_raw': args.require_no_raw, 'steps': []}
    try:
        for label, command in commands:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            (output/(label+'.log')).write_bytes(result.stdout)
            text = result.stdout.decode('utf8', errors='replace')
            print(f'[{label}] exit={result.returncode}\n'+(text if result.returncode else text[-2400:]), flush=True)
            report['steps'].append({'name': label, 'exit_code': result.returncode})
            (output/'summary.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf8')
            if result.returncode: return result.returncode
        report['passed'] = True
        (output/'summary.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf8')
        return 0
    finally:
        # Preserve developer fixtures even when a check fails. Never reset user changes.
        for path, content in saved.items():
            if content is not None: path.write_bytes(content)
            elif path.exists(): path.unlink()


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf8')
    sys.exit(main())
