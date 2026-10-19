"""Freeze reviewed source, evidence, original-preservation checks and local patch.

Does not deploy, change the baseline, rerun replays or access credentials.
"""
import difflib
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / 'review'


def read(name):
    return json.loads((REVIEW / name).read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, data):
    (REVIEW / name).write_text(json.dumps(data, indent=2) + '\n')


def main():
    original = read('BASELINE_SOURCE_INVENTORY.json')
    baseline = Path(original['source'])
    for name, info in original['files'].items():
        assert sha(baseline / name) == info['sha256'], name
    unchanged = ['web/kernel.json', 'browser_adapter.py', 'browser_stream.py',
                 'web/client.js', 'web/financial-worker.js', 'web/strategy-worker.js', 'web/storage.js']
    for name in unchanged:
        assert (ROOT / name).read_bytes() == (baseline / name).read_bytes(), name

    live = read('full-live-regression/BROWSER_RESULTS.json')
    full = read('full-browser-final/BROWSER_RESULTS.json')
    flow = read('candidate-browser-continuation/BROWSER_RESULTS.json')
    upgrade = read('service-worker-upgrade-verified/UPGRADE_RESULTS.json')
    shared = read('candidate-browser/BROWSER_RESULTS.json')['runs']['shared']
    individual = flow['runs']['individual']
    for receipt in (live, full, flow, upgrade):
        assert receipt['status'] == 'PASS', receipt.get('error')
    assert len(live['checks']) == 28 and len(full['checks']) == 28
    assert len(flow['checks']) == 7 and len(upgrade['checks']) == 4
    assert shared['result_hash'] == read('live-before/REPRODUCTION.json')['result_hash']
    assert individual['result_hash'] == read('live-race/LIVE_RACE_AND_INDIVIDUAL.json')['individual_3day']['hash']
    assert flow['original_checkpoint_resume']['hash'] == individual['result_hash']
    assert 'Ran 30 tests' in (REVIEW / 'FINAL_UNIT_TESTS.log').read_text()
    assert (REVIEW / 'FINAL_UNIT_TESTS.log').read_text().rstrip().endswith('OK')
    assert re.search(r'pass 7\b', (REVIEW / 'CONSENT_UNIT_TESTS.log').read_text())
    verification = {
        'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'LOCAL CANDIDATE VERIFIED; PUBLISH APPROVAL REQUIRED',
        'published_changes': False, 'github_changes': False, 'replit_changes': False,
        'test_results': {'python_unittest': {'passed': 30, 'failed': 0, 'skipped': 0},
                         'javascript_unit': {'passed': 7, 'failed': 0},
                         'current_published_build_browser_checks': {'passed': len(live['checks']), 'failed': 0},
                         'candidate_full_browser_checks': {'passed': len(full['checks']), 'failed': 0},
                         'candidate_targeted_flow_checks': {'passed': len(flow['checks']), 'failed': 0},
                         'candidate_old_to_new_upgrade_checks': {'passed': len(upgrade['checks']), 'failed': 0}},
        'real_3day_results': {mode: {'result_hash': result['result_hash'], 'exit_segments': result['trades'],
                                    'matches_current_live_result': True, 'independent_checks': result['independent_checks']}
                             for mode, result in [('shared', shared), ('individual', individual)]},
        'original_checkpoint_resumes_exactly': True,
        'original_checkpoint_financial_hash': flow['original_checkpoint_resume']['hash'],
        'runtime_source_identity': flow['sourceHash'],
        'existing_sources_and_archives_verified_unchanged': len(original['files']),
        'financial_and_storage_sources_byte_identical': unchanged,
        'candidate_build': json.loads((ROOT / 'evidence/STATIC_BUILD.json').read_text()),
        'physical_android_tested': False,
        'earlier_failed_test_attempts_preserved': True,
        'unresolved': ['Owner publication approval', 'Post-publication corrected-build live verification',
                       'Owner original device/click sequence uninspected; one stale-snapshot path confirmed']}
    write('FINAL_VERIFICATION.json', verification)
    files = ['web/app.js', 'web/replay-consent.js', 'web/sw.js', 'web/offline-assets.json',
             'tools/build_static.py', 'tools/verify_staging.py', 'evidence/STATIC_BUILD.json',
             'tests/test_futures_consent.py', 'tests/test_replay_consent.mjs',
             'tools/reproduce_live_consent.py', 'tools/verify_live_consent_race.py',
             'tools/verify_consent_browser.py', 'tools/verify_consent_upgrade.py',
             'tools/finalize_consent_review.py', 'review/CONSENT_FIX_REPORT.md']
    changes = {}
    patch = []
    for name in files:
        current, old = ROOT / name, baseline / name
        after = current.read_text()
        before = old.read_text() if old.exists() else ''
        if before == after:
            continue
        changes[name] = {'bytes': current.stat().st_size, 'sha256': sha(current),
                         'baseline_sha256': sha(old) if old.exists() else None}
        for line in difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                     fromfile='a/' + name if old.exists() else '/dev/null', tofile='b/' + name):
            patch.append(line if line.endswith('\n') else line + '\n\\ No newline at end of file\n')
    patch_file = REVIEW / 'CONSENT_FIX.patch'
    patch_file.write_text(''.join(patch))
    # Check accidental credential patterns in every new/changed source/static
    # asset. Never inspect the environment or secret files.
    patterns = [r'-----BEGIN (?:OPENSSH|RSA|EC|DSA|ENCRYPTED|PRIVATE).*KEY-----',
                r'gh[pousr]_[A-Za-z0-9]{20,}', r'github_pat_[A-Za-z0-9_]{20,}',
                r'AKIA[A-Z0-9]{16}', r'sk_live_[A-Za-z0-9]{16,}']
    findings = [name for name in changes if any(re.search(p, (ROOT / name).read_text()) for p in patterns)]
    assert not findings, 'Potential credential pattern; inspect privately before releasing'
    with tempfile.TemporaryDirectory(prefix='hks-consent-patch-', dir='/tmp') as tmp:
        check = Path(tmp)
        for name in changes:
            old = baseline / name
            if old.exists():
                target = check / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old, target)
        applied = subprocess.run(['patch', '--batch', '-p1', '-i', str(patch_file)], cwd=check,
                                 text=True, capture_output=True)
        assert applied.returncode == 0, applied.stdout + applied.stderr
        for name in changes:
            assert (check / name).read_bytes() == (ROOT / name).read_bytes(), name
    write('CHANGED_FILES_SHA256.json', {'files': changes, 'patch_sha256': sha(patch_file),
            'patch_bytes': patch_file.stat().st_size, 'independent_patch_application_verified': True,
            'credential_pattern_scan': {'files': len(changes), 'findings': 0}})
    write('STATIC_ASSETS_SHA256.json', {str(p.relative_to(ROOT / 'web')):
            {'bytes': p.stat().st_size, 'sha256': sha(p)} for p in sorted((ROOT / 'web').rglob('*')) if p.is_file()})
    evidence = {str(p.relative_to(REVIEW)): {'bytes': p.stat().st_size, 'sha256': sha(p)}
                for p in sorted(REVIEW.rglob('*')) if p.is_file() and p.name != 'EVIDENCE_SHA256.json'}
    write('EVIDENCE_SHA256.json', evidence)
    print(json.dumps({'status': verification['status'], 'changed_files': len(changes),
                      'patch_sha256': sha(patch_file), 'tests': verification['test_results']}, indent=2))


if __name__ == '__main__':
    main()
