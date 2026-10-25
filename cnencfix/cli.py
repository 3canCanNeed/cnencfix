# -*- coding: utf-8 -*-
"""cnencfix CLI —— 中文 Windows 开发环境编码急救包"""
from __future__ import annotations

import argparse
import os
import sys

from . import core

__version__ = "0.1.0"


# ---------- 输出着色 ----------
def _enable_vt() -> None:
    if os.name == "nt":
        os.system("")  # 激活 Windows 控制台的 ANSI 转义支持
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class C:
    def __init__(self, enabled: bool):
        self.ok = "\033[92m" if enabled else ""
        self.warn = "\033[93m" if enabled else ""
        self.err = "\033[91m" if enabled else ""
        self.info = "\033[96m" if enabled else ""
        self.dim = "\033[90m" if enabled else ""
        self.end = "\033[0m" if enabled else ""


c = C(True)


def _fmt_row(file: str, enc: str, extra: str) -> str:
    color = {
        "utf-8": c.ok, "utf-8-sig": c.ok, "gbk": c.warn,
        "binary": c.dim, "empty": c.dim,
    }.get(enc, c.err)
    return f"{color}{enc:12}{c.end}  {extra:36}  {file}"


def cmd_scan(args) -> int:
    files = core.iter_files(args.paths, args.recursive, args.include, args.text_only)
    if not files:
        print(f"{c.err}没有找到可扫描的文件{c.end}")
        return 1
    print(f"{c.info}扫描 {len(files)} 个文件{c.end}\n")
    counts = {}
    for f in files:
        try:
            d = core.detect(f)
        except OSError as e:
            print(f"{c.err}读取失败 {f}: {e}{c.end}")
            continue
        counts[d["encoding"]] = counts.get(d["encoding"], 0) + 1
        if args.suspect_only and "疑似乱码" not in d["note"]:
            continue
        extra = d["note"] or (f"中文占比{d['cjk']:.0%}" if d["cjk"] else "")
        if d["moji"] >= 0.15:
            extra = f"⚠ 疑似乱码({d['moji']:.0%}怪字符) " + extra
        print(_fmt_row(str(f), d["encoding"], extra))
    print(f"\n{c.dim}统计: " + ", ".join(f"{k}×{v}" for k, v in sorted(counts.items())) + c.end)
    return 0


def cmd_conv(args) -> int:
    files = core.iter_files(args.paths, args.recursive, args.include)
    if args.yes or args.dry_run:
        pass
    else:
        print(f"{c.info}目标编码 {args.to}（--dry-run 可预览）{c.end}")
    ok = skip = dry = 0
    for f in files:
        r = core.convert_file(f, to=args.to, bom=args.bom, backup=args.backup, dry=args.dry_run)
        tag = {"ok": c.ok + "OK  " + c.end, "skip": c.dim + "跳过" + c.end, "dry": c.info + "预览" + c.end}[r["status"]]
        print(f"{tag} {r['from']:10} {r['note']:32} {f}")
        ok += r["status"] == "ok"
        skip += r["status"] == "skip"
        dry += r["status"] == "dry"
    print(f"\n{c.ok}转换 {ok}{c.end}  {c.dim}跳过 {skip}{c.end}" + (f"  {c.info}预览 {dry}{c.end}" if dry else ""))
    return 0


def cmd_fix(args) -> int:
    files = core.iter_files(args.paths, args.recursive, args.include)
    ok = skip = dry = 0
    for f in files:
        r = core.fix_file(f, backup=args.backup, dry=args.dry_run)
        tag = {"ok": c.ok + "修复" + c.end, "skip": c.dim + "跳过" + c.end, "dry": c.warn + "预览" + c.end}[r["status"]]
        print(f"{tag} {str(f):48} {r['note']}")
        ok += r["status"] == "ok"
        skip += r["status"] == "skip"
        dry += r["status"] == "dry"
    print(f"\n{c.ok}修复 {ok}{c.end}  {c.dim}跳过 {skip}{c.end}" + (f"  {c.warn}预览 {dry}{c.end}" if dry else ""))
    return 0


def cmd_bom(args) -> int:
    mode = "add" if args.add else "strip"
    files = core.iter_files(args.paths, args.recursive, args.include)
    if args.auto_ps1:
        files = [f for f in files if f.suffix.lower() == ".ps1"]
        mode = "add"
    if not files:
        print(f"{c.err}没有匹配的文件{c.end}")
        return 1
    ok = skip = 0
    for f in files:
        r = core.bom_file(f, mode, dry=args.dry_run)
        tag = {"ok": c.ok + "OK  " + c.end, "skip": c.dim + "跳过" + c.end, "dry": c.info + "预览" + c.end}[r["status"]]
        print(f"{tag} {r['note']:28} {f}")
        ok += r["status"] == "ok"
        skip += r["status"] == "skip"
    print(f"\n{c.ok}处理 {ok}{c.end}  {c.dim}跳过 {skip}{c.end}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="cnencfix",
        description="中文 Windows 开发环境编码急救包：GBK↔UTF-8 转换 / 乱码修复 / BOM 处理（零依赖）",
        epilog="示例:\n"
               "  cnencfix scan . -r --include log,txt     # 递归扫描识别编码\n"
               "  cnencfix conv matlog.log --to utf8       # GBK 日志转 UTF-8\n"
               "  cnencfix conv . -r --to gbk --include csv  # 全目录 CSV 转 GBK\n"
               "  cnencfix fix 乱码.txt --dry-run          # 预览乱码修复\n"
               "  cnencfix bom . -r --auto-ps1             # 给所有 .ps1 补 BOM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--no-color", action="store_true", help="禁用彩色输出")
    ap.add_argument("--version", action="version", version=f"cnencfix {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("paths", nargs="+", help="文件或目录")
        sp.add_argument("-r", "--recursive", action="store_true", help="递归处理目录")
        sp.add_argument("--include", default="", help="扩展名过滤，逗号分隔（如 log,csv）")
        sp.add_argument("--no-color", action="store_true", help="禁用彩色输出")

    p_scan = sub.add_parser("scan", help="识别文件编码（UTF-8/GBK/BOM/二进制/疑似乱码）")
    common(p_scan)
    p_scan.add_argument("--text-only", action="store_true", help="仅扫描常见文本扩展名")
    p_scan.add_argument("--suspect-only", action="store_true", help="仅显示疑似乱码文件")
    p_scan.set_defaults(fn=cmd_scan)

    p_conv = sub.add_parser("conv", help="批量转码 GBK ↔ UTF-8")
    common(p_conv)
    p_conv.add_argument("--to", choices=["utf8", "utf-8", "gbk", "gb2312"], default="utf8", help="目标编码（默认 utf8）")
    p_conv.add_argument("--bom", choices=["keep", "add", "strip"], default="keep", help="UTF-8 BOM 策略")
    p_conv.add_argument("--no-backup", action="store_true", help="不生成 .bak 备份")
    p_conv.add_argument("--dry-run", action="store_true", help="只预览不写入")
    p_conv.add_argument("-y", "--yes", action="store_true", help="跳过提示")
    p_conv.set_defaults(fn=cmd_conv, target_norm="utf-8")

    p_fix = sub.add_parser("fix", help="修复双重编码乱码（UTF-8字节被误解码后再保存）")
    common(p_fix)
    p_fix.add_argument("--no-backup", action="store_true", help="不生成 .bak 备份")
    p_fix.add_argument("--dry-run", action="store_true", help="只预览不写入")
    p_fix.set_defaults(fn=cmd_fix)

    p_bom = sub.add_parser("bom", help="给 UTF-8 文件加/去 BOM（修 PowerShell 5.1 中文乱码）")
    common(p_bom)
    g = p_bom.add_mutually_exclusive_group(required=True)
    g.add_argument("--add", action="store_true", help="添加 BOM")
    g.add_argument("--strip", action="store_true", help="移除 BOM")
    g.add_argument("--auto-ps1", action="store_true", help="给目录下所有 .ps1 补 BOM（加）")
    p_bom.add_argument("--dry-run", action="store_true", help="只预览不写入")
    p_bom.set_defaults(fn=cmd_bom)
    return ap


def main(argv=None) -> int:
    _enable_vt()
    args = build_parser().parse_args(argv)
    if args.no_color:
        global c
        c = C(False)
    if getattr(args, "include", ""):
        args.include = [x for x in args.include.replace("，", ",").split(",") if x.strip()]
    else:
        args.include = []
    if getattr(args, "to", None):  # utf8 → utf-8 归一
        args.to = {"utf8": "utf-8", "utf-8": "utf-8", "gbk": "gbk", "gb2312": "gbk"}[args.to]
    if getattr(args, "backup", None) is None:
        args.backup = True
    if hasattr(args, "no_backup"):
        args.backup = not args.no_backup
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
