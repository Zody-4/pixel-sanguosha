"""Stage selected source and audited resources without publishing or running tests."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'docs/release/runtime-assets.json'
DOCS = ('ASSETS.md', 'ASSET_CREDITS.md', 'ASSET_LICENSE.md', 'DEVELOPMENT.md', 'WINDOWS_RELEASE.md', 'VERIFICATION.md', 'runtime-assets.json')
PUBLIC_TOOLS = ('prepare_open_source.py', 'build_public_windows.py', 'public_windows.spec', 'simulate_ai.py')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def inventory():
    if (ROOT / 'Music/定稿/voice/approved_manifest.json').is_file():
        from prepare_delivery import resource_paths
        paths = sorted(resource_paths())
    else:
        return json.loads(MANIFEST.read_text(encoding='utf-8'))
    fonts = json.loads((ROOT / 'assets/runtime/fonts/sources.json').read_text(encoding='utf-8'))
    known = {f"assets/runtime/fonts/{entry['file']}": entry for entry in fonts['files']}
    voices = json.loads((ROOT / 'Music/定稿/voice/approved_manifest.json').read_text(encoding='utf-8-sig'))
    effects = json.loads((ROOT / 'Music/定稿/sfx/approved_manifest.json').read_text(encoding='utf-8-sig'))
    from xssgkpz.data.cards import CARD_KINDS, CardCategory
    equipment = {kind.kind_id for kind in CARD_KINDS if kind.category is CardCategory.EQUIPMENT}
    voice_map = {f"Music/定稿/voice/{item['file']}": item for item in voices['lines']}
    effect_map = {f"Music/定稿/sfx/{item['file']}": item for item in effects['sounds']}
    # Verify final effects against the recorded CC0 source and production hashes.
    cleared_effects = {}
    for relative, item in effect_map.items():
        version = item.get('source_version', '')
        if version not in {'v37', 'v38', 'v40', 'v41'}:
            continue
        production = json.loads((ROOT / f'Music/outputs/{version}/manifest.json').read_text(encoding='utf-8'))
        originals = production.get('sources', {})
        for source, record in originals.items():
            original = ROOT / 'Music/work/kenney' / source
            if record.get('license') != 'Kenney CC0' or sha(original.read_bytes()) != record['sha256']:
                raise ValueError('CC0 source verification failed: ' + source)
        candidates = production.get('sounds', [])
        if not originals or not any(candidate.get('sha256') == item['sha256'] for candidate in candidates):
            raise ValueError('Final effect not matched to production: ' + relative)
        if sha((ROOT / relative).read_bytes()) != item['sha256']:
            raise ValueError('Final effect content changed: ' + relative)
        cleared_effects[relative] = dict(version=version, originals=originals)
    for name in ('kenney-casino.txt', 'kenney-impact.txt', 'kenney-rpg.txt'):
        relative = f'Music/定稿/sfx/licenses/{name}'
        data = (ROOT / relative).read_bytes()
        if b'CC0' not in data:
            raise ValueError('CC0 license missing: ' + relative)
        paths.append(relative)
    entries = []
    for relative in paths:
        data = (ROOT / relative).read_bytes()
        entry = dict(path=relative, bytes=len(data), sha256=sha(data),
                     status='pending', license=None, evidence=[], source_url=None)
        if relative in known:
            upstream = known[relative]
            if entry['sha256'] != upstream['sha256']:
                raise ValueError('Font differs from pinned upstream: ' + relative)
            entry.update(status='redistributable', license='OFL-1.1', source_url=upstream['source'],
                         evidence=['assets/runtime/fonts/sources.json', 'Bundled original OFL license'])
        elif relative == 'assets/runtime/fonts/sources.json':
            entry.update(status='redistributable', license='MIT', evidence=['Pinned font metadata; no private paths'])
        elif relative.endswith('.png'):
            is_identity = relative.startswith('assets/references/身份卡/')
            is_card_base = relative.startswith('assets/runtime/cards/v06/layers/底图/')
            kind = Path(relative).stem if is_card_base else None
            if is_identity:
                entry.update(origin='external_nonoriginal',
                             evidence=['Author confirmation 2026-10-08: identity cards are not original',
                                       'Original creator/link and redistribution license not provided'])
            elif kind == 'sha':
                entry.update(origin='external_reference_nonoriginal',
                             evidence=['Author confirmation 2026-10-08: Strike illustration character appearance is referenced, not original',
                                       'Reference identity and permission not verified'])
            elif kind in equipment:
                entry.update(origin='external_nonoriginal',
                             evidence=['Author confirmation 2026-10-08: weapon/equipment imagery is not original',
                                       'All equipment bases held pending; original creator/link not provided'])
            else:
                is_rendered_layer = relative.startswith('assets/runtime/cards/v06/layers/') and not is_card_base
                entry.update(status='redistributable', license='CC-BY-4.0',
                             origin='project_rendered_component' if is_rendered_layer else 'author_confirmed_ai',
                             attribution='ZDY / 像素三国卡牌战；AI生成及项目组装',
                             evidence=['Author confirmation 2026-10-08: 25 portraits, tricks, small components and all other images are AI-original',
                                       'Separate text/suit/rank layers do not contain the external illustration' if is_rendered_layer else 'Runtime resource mapped to author-confirmed category',
                                       'Permission applies only to rights the project author can grant; see ASSET_LICENSE.md'])
            if entry['status'] == 'pending':
                entry['source_description'] = 'Author clarification 2026-10-08: classic old-edition Sanguosha card imagery; exact original source and redistribution rights unverified'
        elif relative.endswith('_bgm.wav'):
            version = 'v19' if 'menu_' in relative else 'v30'
            entry['evidence'] = [f'Stable Audio 3 Small-Music: {version}/manifest.json, source_audio=null',
                                 'Final loop selection v31; model/output terms pending']
        elif relative in voice_map:
            item = voice_map[relative]
            entry['evidence'] = ['Qwen3-TTS Base / VoiceDesign generation chain',
                                 'Source version: ' + item.get('source_version', 'unknown'),
                                 'No general asset redistribution grant inferred from user approval']
        elif relative.startswith('Music/定稿/sfx/licenses/'):
            entry.update(status='redistributable', license='CC0-1.0', evidence=['Original Kenney package license'],
                         source_url='https://kenney.nl/assets')
        elif relative in cleared_effects:
            record = cleared_effects[relative]
            entry.update(status='redistributable', license='CC0-1.0',
                         source_url='https://kenney.nl/assets',
                         evidence=[f"Final SHA256 matches {record['version']} production manifest",
                                   'All recorded Kenney source SHA256 values matched local originals; original CC0 licenses bundled'],
                         original_sources=record['originals'])
        elif relative in effect_map:
            item = effect_map[relative]
            entry['source_url'] = item.get('source_url')
            entry['evidence'] = ['Source version: ' + item.get('source_version', 'unknown')]
            if item.get('asset_license_verified') is False:
                entry['evidence'].append('External recording converted to WAV; asset license explicitly unverified')
                entry.update(origin='external_audio_conversion',
                             source_page=item.get('source_page'),
                             original_sha256=item.get('original_sha256'),
                             author_instruction='Retain existing sound; credit source and provide an infringement-removal contact via GitHub Issues',
                             attribution_notice='See docs/release/ASSET_CREDITS.md; attribution is not a redistribution license')
            else:
                entry['evidence'].append('Kenney CC0 production chain; per-file attribution verification pending')
        else:
            entry['evidence'] = ['Internal approval metadata; kept private until sanitized and rights cleared']
        entries.append(entry)
    return dict(date='2026-10-08',
                author_statement='25 portraits, tricks, small components and other imagery AI-original; Strike appearance, identity cards and equipment not original. Keep two external sounds with attribution and removal contact.',
                files=entries)


def patterns():
    # Return labels and locations only, never matched secrets or private addresses.
    return {
        'private_contact': re.compile(rb'vx\xe8\x81\x94\xe7\xb3\xbb'),
        'absolute_user_path': re.compile(rb'[A-Za-z]:[\\/]+Users[\\/]+[^\\/\r\n\"\s]+', re.I),
        'github_token': re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}'),
        'api_secret': re.compile(rb'sk-[A-Za-z0-9_-]{24,}'),
        'private_key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
        'credential_url': re.compile(rb'https?://[^\s/:]+:[^\s/@]+@'),
    }


def findings(payloads):
    result = []
    for name, data in payloads.items():
        for label, expression in patterns().items():
            count = len(expression.findall(data))
            if count:
                result.append(dict(path=name, kind=label, count=count))
    return result


def history_audit():
    if not (ROOT / '.git').exists():
        return dict(scope='No repository history in this snapshot', findings=[])
    output = subprocess.check_output(['git', 'rev-list', '--objects', '--all'], cwd=ROOT)
    objects = {}
    for line in output.decode('utf-8', errors='replace').splitlines():
        oid, _, path = line.partition(' ')
        objects[oid] = path
    process = subprocess.Popen(['git', 'cat-file', '--batch'], cwd=ROOT,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    matches, scanned = [], 0
    try:
        for oid, path in objects.items():
            process.stdin.write((oid + '\n').encode()); process.stdin.flush()
            header = process.stdout.readline().split()
            size = int(header[2])
            data = process.stdout.read(size)
            process.stdout.read(1)
            if header[1] not in (b'blob', b'commit', b'tag'):
                continue
            scanned += 1
            for found in findings({path or '<commit-or-tag>': data}):
                matches.append(dict(object=oid, **found))
    finally:
        process.stdin.close(); process.stdout.close(); process.wait()
    return dict(scope='All objects reachable from local git --all refs, including commit metadata; no remote-only refs',
                objects_scanned=scanned, findings=matches,
                limitations='Pattern scan only; does not detect every secret, OCR screenshots, or inspect remote configuration')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--include-unverified-assets', action='store_true',
                        help='Export complete source at user request, retaining pending rights and attribution notices')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error('Output must be new; existing deliveries are preserved')
    manifest = inventory()
    write_json(MANIFEST, manifest)
    paths = {'README.md', 'LICENSE', 'NOTICE.md', 'requirements.txt', 'requirements-build.txt', 'run_game.py', '.gitignore'}
    paths.update(f'docs/release/{name}' for name in DOCS)
    paths.update(f'tools/{name}' for name in PUBLIC_TOOLS)
    paths.add('docs/product/需求规则追踪矩阵.md')
    paths.add('docs/release/screenshots/main-menu.png')
    paths.update(path.relative_to(ROOT).as_posix() for path in (ROOT / '.github').rglob('*') if path.is_file())
    for folder in ('src', 'tests'):
        paths.update(path.relative_to(ROOT).as_posix() for path in (ROOT / folder).rglob('*.py')
                     if '__pycache__' not in path.parts)
    source = {path: (ROOT / path).read_bytes() for path in sorted(paths)}
    source['AGENTS.md'] = ('# Public source collaboration\n\nRead README.md and docs/release/ASSETS.md first. '
        'Preserve existing gameplay. Run tests only when the user requests them. '
        'Do not publish pending assets, private data or old repository history.\n').encode()
    for path, data in source.items():
        if path.endswith('.py'):
            ast.parse(data.decode('utf-8-sig'), filename=path)
    public, private = dict(source), dict(source)
    for entry in manifest['files']:
        path = ROOT / entry['path']
        if not path.is_file():
            if entry['status'] == 'redistributable':
                raise FileNotFoundError(entry['path'])
            continue
        data = path.read_bytes()
        if sha(data) != entry['sha256']:
            raise ValueError('Resource hash mismatch: ' + entry['path'])
        private[entry['path']] = data
        if entry['status'] == 'redistributable' or args.include_unverified_assets:
            public[entry['path']] = data
    matches = findings(public)
    if matches:
        raise ValueError('Public snapshot contains potential private information: ' + str(matches))
    history = history_audit()
    output.mkdir(parents=True)
    sums = []
    private_complete = all(entry['path'] in private for entry in manifest['files'])
    private_name = 'private-full-source' if private_complete else 'private-incomplete-source'
    public_name = 'publication-source' if args.include_unverified_assets else 'public-source'
    for name, payloads in ((public_name, public), (private_name, private)):
        if name.startswith('private'):
            payloads['DO_NOT_UPLOAD.txt'] = b'PRIVATE LOCAL REVIEW ONLY: contains assets with unverified redistribution rights.\n'
        target = output / name
        for relative, data in payloads.items():
            path = target / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        file_manifest = dict(kind=name, complete_game_resources=private_complete and (name.startswith('private') or args.include_unverified_assets),
                             public_upload_allowed=not name.startswith('private'),
                             unverified_assets_included=args.include_unverified_assets and not name.startswith('private'),
                             rights_cleared_for_all_assets=False,
                             files=[dict(path=p, bytes=len(d), sha256=sha(d)) for p, d in sorted(payloads.items())])
        write_json(target / 'source-manifest.json', file_manifest)
        archive = output / (name + '.zip')
        with ZipFile(archive, 'x', ZIP_DEFLATED) as bundle:
            for path in sorted(target.rglob('*')):
                if path.is_file():
                    bundle.write(path, Path(name) / path.relative_to(target))
        sums.append(f'{sha(archive.read_bytes())}  {archive.name}')
    (output / 'SHA256SUMS.txt').write_text('\n'.join(sums) + '\n', encoding='utf-8')
    report = dict(public_files=len(public), private_files=len(private), private_resources_complete=private_complete,
                  public_scan_findings=matches,
                  resource_status=dict(Counter(e['status'] for e in manifest['files'])),
                  history=history, tests_run=False, game_run=False)
    write_json(output / 'private-audit.json', report)
    print(json.dumps({key: value for key, value in report.items() if key != 'history'}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
