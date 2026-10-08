from pathlib import Path
import json

root = Path(SPECPATH).resolve().parent
entries = json.loads((root / 'docs/release/runtime-assets.json').read_text(encoding='utf-8'))['files']
datas = [(str(root / entry['path']), str(Path(entry['path']).parent)) for entry in entries]
a = Analysis([str(root / 'run_game.py')], pathex=[str(root / 'src')],
             binaries=[], datas=datas, hiddenimports=[], hookspath=[],
             runtime_hooks=[], excludes=[])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='xssgkpz',
          debug=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='xssgkpz')
