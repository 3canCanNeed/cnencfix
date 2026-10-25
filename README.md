# cnencfix

中文 Windows 开发环境编码急救包。零依赖、单命令，专治 GBK ↔ UTF-8 问题。

## 为什么需要它

如果你在中文 Windows 上写代码，一定遇到过这些：

| 场景 | 症状 | cnencfix 命令 |
|------|------|---------------|
| PowerShell 5.1 读 UTF-8 脚本 | 中文字符串变成乱码 | `cnencfix bom file.ps1 --add` |
| MATLAB / CMD 输出的 GBK 日志 | 在 Git Bash / VS Code 里全乱码 | `cnencfix conv log.log --to utf8` |
| 文件被错误编码打开又保存 | 内容变成乱码（如"鏃犳硶鍏抽棴"） | `cnencfix fix file.txt` |
| 拿到一批文件不知道编码 | 需要快速摸底 | `cnencfix scan . -r` |

## 安装

```bash
pip install cnencfix
# 或直接从源码
pip install git+https://github.com/3canCanNeed/cnencfix.git
```

## 使用

### 扫描：识别编码

```bash
cnencfix scan .                        # 当前目录
cnencfix scan logs/ -r                 # 递归子目录
cnencfix scan . -r --include log,csv   # 只看指定扩展名
cnencfix scan . -r --suspect-only      # 只显示疑似乱码文件
```

输出示例：
```
扫描 3 个文件

gbk           GBK/GB2312                            dogfood\matlab.log
utf-8         中文占比95%                               dogfood\normal.md
utf-8         ⚠ 疑似乱码(100%怪字符)                     dogfood\bad.txt

统计: gbk×1, utf-8×2
```

### 转换：GBK ↔ UTF-8

```bash
cnencfix conv matlab.log --to utf8          # 单文件转 UTF-8
cnencfix conv logs/ -r --to utf8            # 递归全目录
cnencfix conv data/ -r --to gbk --include csv  # 只转 CSV 为 GBK（给 Excel 用）
cnencfix conv . -r --to utf8 --bom add      # 转 UTF-8 并加 BOM
cnencfix conv . -r --dry-run                # 只预览不写入
```

### 修复乱码：逆推双重编码

修复"UTF-8 文件被程序用 GBK 打开再存回 UTF-8"产生的乱码（如 `鏃犳硶鍏抽棴` → `无法关闭`）。

```bash
cnencfix fix file.txt              # 修复
cnencfix fix . -r --dry-run       # 递归预览
```

自动尝试 GBK → UTF-8 逆推，仅在能恢复出合法 UTF-8 时才写回。正常中文不会被误改。

### BOM 处理：修 PowerShell 5.1

PowerShell 5.1 只认带 BOM 的 UTF-8；无 BOM 的 UTF-8 脚本里的中文必然乱码。

```bash
cnencfix bom script.ps1 --add       # 给单个文件加 BOM
cnencfix bom . -r --auto-ps1       # 递归给所有 .ps1 加 BOM
cnencfix bom . -r --strip          # 递归移除 BOM
```

## 技术原理

- **编码识别**：UTF-8 严格解码验证（通过即高置信）→ GBK 严格解码 + 中文占比验证（GBK 几乎什么都能解，必须看内容）→ BOM 检查
- **乱码检测**：latin-1 风格签名字符密度（Â/å/æ 等）+ GBK 逆推 round-trip 验证
- **乱码修复**：多编码逆推（GBK/latin-1/cp1252），取最优恢复结果；有"正常文本不可被破坏"安全验证

## 测试

29 个单元测试覆盖：编码检测、转换往返、BOM 操作、乱码修复、CLI 端到端、误修复安全检查。

```bash
python -m unittest discover -s tests
```

## License

MIT
