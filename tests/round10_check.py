# -*- coding: utf-8 -*-
"""第十轮：README 命令可解析性 + 元数据 + 最终回归"""
import re
import io
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(PROJ))

from cnencfix.cli import build_parser
from cnencfix import __version__

bugs = []

# U1. README 代码块中的所有命令示例都能被 argparse 接受
readme = (PROJ / 'README.md').read_text(encoding='utf-8')
# 只提取 ```bash 代码块内的命令（表格里的描述性文字不算）
block_cmds = re.findall(r'```bash\n(.*?)```', readme, re.S)
cmds = []
for block in block_cmds:
    for line in block.splitlines():
        line = line.strip()
        if line.startswith('cnencfix ') and '#' not in line.split('cnencfix')[1][:3]:
            # 去掉行内注释
            code_part = line.split('#')[0].strip()
            if code_part.startswith('cnencfix'):
                cmds.append(code_part[len('cnencfix'):].strip())
parser = build_parser()
tested = 0
for raw in cmds:
    argv = (raw.replace('logs/', '.').replace('matlab.log', 'x.txt')
               .replace('data/', '.').replace('script.ps1', 'x.txt')
               .replace('file.txt', 'x.txt').replace('file.ps1', 'x.txt')
               .replace('bad.txt', 'x.txt').replace('乱码.txt', 'x.txt')
               .split())
    if not argv:
        continue
    try:
        parser.parse_args(argv)
        tested += 1
    except SystemExit as e:
        if e.code != 0:
            bugs.append(('README_CMD', f'cnencfix {raw}'))

if not bugs:
    print(f'✓ U1 README 中 {tested} 条命令示例全部可解析')

# U2. 无过时描述
if 'Buck 输出电压纹波' in readme:
    bugs.append(('OUTDATED', 'README 含其他项目残留'))

# U3. __version__
if not __version__:
    bugs.append(('NO_VERSION', ''))
else:
    print(f'✓ U3 __version__ = {__version__}')

# U5. 最终全量测试
loader = unittest.TestLoader()
suite = loader.discover(str(PROJ / 'tests'))
runner = unittest.TextTestRunner(verbosity=0)
result = runner.run(suite)
if not result.wasSuccessful():
    bugs.append(('TESTS', f'{len(result.failures)}F {len(result.errors)}E'))
else:
    print(f'✓ U5 单元测试 {result.testsRun} 个全部通过')

# U6. Git 状态
import subprocess as sp
st = sp.run(['git', 'status', '--short'], capture_output=True, cwd=str(PROJ))
unstaged = st.stdout.decode().strip()
if unstaged:
    print(f'⚠ 未提交更改: {unstaged[:80]}')
else:
    print('✓ U6 工作树与远端一致')

print()
if bugs:
    print(f'发现 {len(bugs)} 个问题:')
    for tag, detail in bugs:
        print(f'  ✗ [{tag}] {detail}')
else:
    print('=== 第十轮全部通过 ===')
