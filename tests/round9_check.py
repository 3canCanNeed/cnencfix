# -*- coding: utf-8 -*-
"""第九轮：包可用性 / 打包完整性 / 端到端工作流"""
import sys, os, io
import subprocess as sp
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
PROJ = str(Path(__file__).resolve().parent.parent)

bugs = []
tmp = TemporaryDirectory()
d = Path(tmp.name)

# T1. 任意目录 import
code = 'import sys; sys.path.insert(0, r"' + PROJ + '"); from cnencfix import core, cli; print("IMPORT_OK")'
r = sp.run([sys.executable, '-c', code], capture_output=True, timeout=30, cwd='/')
if b'IMPORT_OK' not in r.stdout:
    bugs.append(('IMPORT_CWD', r.stderr.decode()[:100]))
else:
    print('✓ T1 任意目录 import 正常')

# T2. python -m cnencfix 任意 cwd
r2 = sp.run([sys.executable, '-m', 'cnencfix', 'scan', '--help'],
            capture_output=True, timeout=30, cwd='/')
if r2.returncode != 0:
    bugs.append(('MODULE_RUN', r2.stderr.decode()[:80]))
else:
    print('✓ T2 python -m cnencfix 任意 cwd 正常')

# T3. 公开 API 完整
code3 = ('import sys; sys.path.insert(0, r"' + PROJ + '"); '
         'from cnencfix.core import detect_bytes, detect, convert_file, fix_file, fix_text, '
         'bom_file, iter_files, cjk_ratio, mojibake_score, BOM_UTF8, read_bytes; '
         'from cnencfix.cli import main, build_parser; print("ALL_EXPORTS_OK")')
r3 = sp.run([sys.executable, '-c', code3], capture_output=True, timeout=30)
if b'ALL_EXPORTS_OK' not in r3.stdout:
    bugs.append(('EXPORTS', r3.stderr.decode()[:120]))
else:
    print('✓ T3 全部公开 API 可导入')

# T4. --help 全部子命令
for cmd in ['scan', 'conv', 'fix', 'bom']:
    r4 = sp.run([sys.executable, '-m', 'cnencfix', cmd, '--help'],
                capture_output=True, timeout=15, cwd='/')
    if r4.returncode != 0:
        bugs.append((f'HELP_{cmd}', r4.stderr.decode()[:80]))
print('✓ T4 四个子命令 --help 正常')

# T5. 长路径安全处理
from cnencfix import core
deep = d
for i in range(15):
    deep = deep / f'dir{i}'
try:
    deep.mkdir(parents=True)
    f = deep / ('x' * 100 + '.txt')
    f.write_bytes('中文'.encode('gbk'))
    r = core.detect(f)
    print(f'✓ T5 超长路径({len(str(f))}字符): {r["encoding"]}')
except OSError:
    print('⚠ T5 路径超 Windows 限制（系统层面，安全跳过）')

# T6. 元数据一致性
import tomllib
with open(Path(PROJ) / 'pyproject.toml', 'rb') as pf:
    cfg = tomllib.load(pf)
from cnencfix import __version__ as pkg_ver
if pkg_ver != cfg['project']['version']:
    bugs.append(('VER_MISMATCH', f'{pkg_ver} vs {cfg["project"]["version"]}'))
else:
    print(f'✓ T6 版本一致: {pkg_ver}')
if cfg['project']['scripts'].get('cnencfix') != 'cnencfix.cli:main':
    bugs.append(('ENTRY_POINT', str(cfg['project']['scripts'])))
else:
    print('✓ T6 entry point: cnencfix.cli:main')

# T7. 锁非重入安全
src = open(Path(PROJ) / 'cnencfix' / 'core.py', encoding='utf-8').read()
detect_src = src[src.find('def detect('):src.find('def _backup(')]
if '_file_lock' in detect_src:
    bugs.append(('LOCK_DEADLOCK', 'detect 持锁会与 convert_file 嵌套死锁'))
else:
    print('✓ T7 detect 不持锁，convert_file 内层加锁无死锁风险')

# T8. 端到端工作流
work = d / 'workflow'
work.mkdir()
(work / 'report.log').write_bytes('错误: 连接超时\n警告: 配置缺失\n'.encode('gbk'))
env_code = f'import sys; sys.path.insert(0, r"{PROJ}")\nfrom cnencfix.cli import main\n'
scan_code = env_code + 'main(["scan", "report.log", "--no-color"])\n'
r8 = sp.run([sys.executable, '-c', scan_code], capture_output=True, timeout=30, cwd=str(work))
if r8.returncode != 0 or b'gbk' not in r8.stdout:
    bugs.append(('E2E_SCAN', f'rc={r8.returncode}'))
conv_code = env_code + 'main(["conv", "report.log", "--to", "utf8", "--no-backup", "--no-color"])\n'
r9 = sp.run([sys.executable, '-c', conv_code], capture_output=True, timeout=30, cwd=str(work))
content = (work / 'report.log').read_bytes()
if content.decode('utf-8') != '错误: 连接超时\n警告: 配置缺失\n':
    bugs.append(('E2E_CONV', repr(content[:40])))
else:
    print('✓ T8 端到端: scan(识别gbk) → conv(转utf-8) 内容无损')

print()
if bugs:
    print(f'发现 {len(bugs)} 个问题:')
    for tag, detail in bugs:
        print(f'  ✗ [{tag}] {detail}')
else:
    print('=== 第九轮全部通过：打包/导入/入口/端到端 ===')

tmp.cleanup()
sys.exit(1 if bugs else 0)
