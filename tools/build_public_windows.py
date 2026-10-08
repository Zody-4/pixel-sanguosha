"""Build a Windows package; pending assets require explicit local-private review mode."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import types
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--private-review', action='store_true')
    parser.add_argument('--include-unverified-assets', action='store_true',
                        help='User-requested full distribution with pending third-party rights disclosed')
    args = parser.parse_args()
    output = args.output.resolve()
    if sys.platform != 'win32':
        parser.error('Windows host required')
    if output.exists():
        parser.error('Output must be new')
    manifest = json.loads((ROOT / 'docs/release/runtime-assets.json').read_text(encoding='utf-8'))
    pending = [e['path'] for e in manifest['files'] if e['status'] != 'redistributable']
    if args.private_review and args.include_unverified_assets:
        parser.error('Choose private review or user-requested attributed distribution')
    if pending and not (args.private_review or args.include_unverified_assets):
        parser.error(f'{len(pending)} assets pending: public full-game build is blocked; review ASSETS.md')
    for entry in manifest['files']:
        path = ROOT / entry['path']
        if not path.is_file() or sha(path) != entry['sha256']:
            parser.error('Missing or altered runtime resource: ' + entry['path'])
    if b'vx\xe8\x81\x94\xe7\xb3\xbb' in (ROOT / 'src/xssgkpz/shell_layout.py').read_bytes():
        parser.error('Private contact remains in game source')
    output.mkdir(parents=True)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm',
               '--distpath', str(output / 'app'), '--workpath', str(output / 'work'),
               str(ROOT / 'tools/public_windows.spec')]
    with (output / 'build.log').open('w', encoding='utf-8') as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        print('Build failed; inspect build.log')
        return result.returncode
    app = output / 'app/xssgkpz'
    # Inspect the frozen module itself: a source edit alone does not sanitize an old exe.
    from PyInstaller.archive.readers import CArchiveReader
    archive_reader = CArchiveReader(str(app / 'xssgkpz.exe'))
    embedded = next(name for name in archive_reader.toc if name.endswith('.pyz'))
    code = archive_reader.open_embedded_archive(embedded).extract('xssgkpz.shell_layout')
    strings = []
    def collect_constants(module):
        for value in module.co_consts:
            if isinstance(value, str):
                strings.append(value)
            elif isinstance(value, types.CodeType):
                collect_constants(value)
    collect_constants(code)
    if '问题反馈：项目 GitHub Issues' not in strings or any('vx' + '联系' in s for s in strings):
        raise ValueError('Frozen executable contact cleanup did not pass')
    for entry in manifest['files']:
        path = app / '_internal' / entry['path']
        if not path.is_file() or sha(path) != entry['sha256']:
            raise ValueError('Bundled resource differs: ' + entry['path'])
    for name in ('LICENSE', 'NOTICE.md'):
        shutil.copy2(ROOT / name, app / name)
    docs = app / 'docs/release'
    docs.mkdir(parents=True)
    for name in ('WINDOWS_RELEASE.md', 'ASSETS.md', 'ASSET_CREDITS.md', 'ASSET_LICENSE.md', 'VERIFICATION.md', 'runtime-assets.json'):
        shutil.copy2(ROOT / 'docs/release' / name, docs / name)
    license_root = app / 'third-party-licenses'
    license_root.mkdir()
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if not python_license.is_file():
        raise FileNotFoundError('Python LICENSE.txt must accompany runtime')
    shutil.copy2(python_license, license_root / 'Python-LICENSE.txt')
    collected = []
    for distribution in importlib.metadata.distributions():
        for relative in distribution.files or ():
            parts = str(relative).lower()
            if any(word in Path(parts).name for word in ('license', 'copying', 'notice')):
                path = Path(distribution.locate_file(relative))
                if path.is_file():
                    # Preserve the package-relative license hierarchy without '..'.
                    target = license_root / distribution.metadata['Name'] / Path(*[p for p in Path(relative).parts if p not in ('.', '..')])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
                    collected.append(target.relative_to(app).as_posix())
    environment = subprocess.check_output([sys.executable, '-m', 'pip', 'freeze'], text=True)
    (docs / 'build-environment.txt').write_text(environment, encoding='utf-8')
    (app / '启动说明.txt').write_text(
        '完整解压，运行 xssgkpz.exe，保留 _internal。无需安装 Python。\n'
        '反馈使用 GitHub Issues。诊断日志只在本地，不自动上传。\n'
        '本构建已含 PC 诊断，不需旧补丁；不宣称白屏已经修复。\n'
        + ('本地审阅候选，含未核实素材，禁止上传或公开分发。\n' if args.private_review else ''), encoding='utf-8-sig')
    if args.include_unverified_assets:
        (app / '素材与版权说明.txt').write_text(
            '代码按MIT开源，素材不是全部按MIT开放。\n'
            '杀的参考形象、身份卡和装备来自老版经典卡牌形象，未声明原创或已取得第三方授权。\n'
            '治疗／受伤录音转换自无名杀；原链接、处理与权利联系见docs/release/ASSET_CREDITS.md。\n'
            '本包按用户要求保留既有素材；标注来源和如有侵权联系删除不代替再分发许可。\n', encoding='utf-8-sig')
    if args.private_review:
        (app / 'DO_NOT_UPLOAD.txt').write_text('PRIVATE LOCAL REVIEW ONLY: pending asset rights.\n', encoding='utf-8')
    files = [dict(path=p.relative_to(app).as_posix(), bytes=p.stat().st_size, sha256=sha(p))
             for p in sorted(app.rglob('*')) if p.is_file()]
    metadata = dict(kind='private-review' if args.private_review else 'windows-release',
                    assets_verified=len(manifest['files']), pending_assets=len(pending),
                    rights_cleared_for_all_assets=not pending,
                    unverified_assets_included=args.include_unverified_assets,
                    license_files=collected, public_upload_allowed=not args.private_review,
                    contact_cleanup_verified=True,
                    launched=False, device_verified=False, tests_run=False, files=files)
    (app / 'build-manifest.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    archive = output / ('xssgkpz-windows-private-review.zip' if args.private_review else 'xssgkpz-windows.zip')
    with ZipFile(archive, 'x', ZIP_DEFLATED) as bundle:
        for path in sorted(app.rglob('*')):
            if path.is_file():
                bundle.write(path, Path('xssgkpz') / path.relative_to(app))
    (output / 'SHA256SUMS.txt').write_text(f'{sha(archive)}  {archive.name}\n', encoding='utf-8')
    print(json.dumps(dict(archive=str(archive), resources=len(manifest['files']),
                          public_upload_allowed=not args.private_review, license_files=len(collected)), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
