# -*- coding: utf-8 -*-
"""cnencfix.core —— 编码检测 / 转换 / 乱码修复 / BOM 处理（零依赖，仅标准库）"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional, Tuple

# 全局文件写锁：防止多线程并发读-写同一文件时数据被截断
_file_lock = threading.Lock()

BOM_UTF8 = b"\xef\xbb\xbf"
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".godot", "venv", ".venv", ".idea", ".vscode"}
TEXT_EXT = {
    ".txt", ".md", ".log", ".csv", ".json", ".xml", ".yml", ".yaml", ".ini", ".cfg",
    ".py", ".js", ".ts", ".html", ".css", ".c", ".h", ".cpp", ".hpp", ".java",
    ".gd", ".m", ".ps1", ".bat", ".cmd", ".srt", ".tex", ".sql", ".svg",
}

# UTF-8 字节被按 latin-1 误解读时产生的典型"签名"字符（Âåæ…）
_MOJIBAKE_CHARS = set("ÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ")


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (
        0x4E00 <= o <= 0x9FFF      # CJK 统一表意
        or 0x3400 <= o <= 0x4DBF   # 扩展A
        or 0x3000 <= o <= 0x303F   # CJK 标点
        or 0xFF00 <= o <= 0xFFEF   # 全角
    )


def cjk_ratio(s: str) -> float:
    """中文字符占非空白字符的比例（空文本返回 0）"""
    chars = [c for c in s if not c.isspace()]
    if not chars:
        return 0.0
    return sum(1 for c in chars if _is_cjk(c)) / len(chars)


def mojibake_score(s: str) -> float:
    """检测文本是否为乱码。三层判据：
    1. U+0080-BF 低区字符密度 >= 0.25（latin-1 乱码强特征；自然语言≈0%）
    2. 连续 >=3 个签名 mojibake 字符的密度 >= 0.10
    3. GBK 逆推验证（GBK 误读产生的 CJK 区乱码）
    """
    chars = [c for c in s if not c.isspace()]
    if not chars:
        return 0.0
    low_special = sum(1 for c in chars if 0x80 <= ord(c) <= 0xBF)
    low_ratio = low_special / len(chars)
    if low_ratio >= 0.25:
        return low_ratio
    consecutive = 0
    total_consecutive = 0
    low_in_runs = 0
    for c in chars:
        if c in _MOJIBAKE_CHARS:
            consecutive += 1
            if 0x80 <= ord(c) <= 0xBF:
                low_in_runs += 1
        else:
            if consecutive >= 3:
                total_consecutive += consecutive
            consecutive = 0
    if consecutive >= 3:
        total_consecutive += consecutive
    consecutive_ratio = total_consecutive / len(chars)
    # 连续 run 中含低区字符（Â¸­）才认定为 latin-1 乱码；纯高位重音（àèìòù）不是
    if consecutive_ratio >= 0.10 and low_in_runs >= 2:
        return consecutive_ratio
    r = fix_text(s)
    if r is not None:
        return 1.0
    return 0.0


def detect_bytes(b: bytes) -> dict:
    """识别一段字节：返回 {encoding, bom, cjk, moji, note}"""
    info = {"encoding": "unknown", "bom": False, "cjk": 0.0, "moji": 0.0, "note": ""}
    if not b.strip():
        info["encoding"] = "empty"
        return info
    if b.startswith(BOM_UTF8):
        info["bom"] = True
        info["encoding"] = "utf-8-sig"
        b = b[len(BOM_UTF8):]
    elif b.startswith(b"\xff\xfe") or b.startswith(b"\xfe\xff"):
        info["bom"] = True
        info["encoding"] = "utf-16"
        info["note"] = "UTF-16 带 BOM"
        return info
    if b"\x00" in b:
        info["encoding"] = "binary"
        return info
    try:
        t = b.decode("utf-8")
        if info["encoding"] != "utf-8-sig":
            info["encoding"] = "utf-8"
        info["cjk"] = round(cjk_ratio(t), 3)
        info["moji"] = round(mojibake_score(t), 3)
        if info["moji"] >= 0.15 and info["cjk"] < 0.1:
            info["note"] = "合法UTF-8但疑似乱码（UTF-8字节曾被误解码后再保存），试试 cnencfix fix"
        return info
    except UnicodeDecodeError:
        pass
    try:
        t = b.decode("gbk")
        ratio = cjk_ratio(t)
        info["cjk"] = round(ratio, 3)
        if ratio >= 0.05 or len(t) < 8:
            info["encoding"] = "gbk"
            info["note"] = "GBK/GB2312"
        else:
            info["encoding"] = "binary?"
            info["note"] = "可按GBK解码但几乎无中文，可能为二进制"
        return info
    except UnicodeDecodeError:
        info["encoding"] = "unknown"
        info["note"] = "既非UTF-8也非GBK"
        return info


def read_bytes(path):
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"不是文件或不存在: {p}")
    with open(p, "rb") as f:
        return f.read()


def detect(path, sample: int = 65536) -> dict:
    """检测文件编码，永不崩溃"""
    p = Path(path)
    d = {"file": str(p)}
    try:
        if not p.is_file():
            d.update({"encoding": "error", "note": "不是文件或不存在"})
            d["size"] = 0
            return d
        with open(p, "rb") as f:
            b = f.read(sample)
    except (OSError, PermissionError) as e:
        d.update({"encoding": "error", "note": f"读取失败: {e.strerror or e}"})
        d["size"] = 0
        return d
    d.update(detect_bytes(b))
    d["size"] = p.stat().st_size
    return d


def _backup(path: Path) -> Path:
    """备份文件：始终用 .bak（覆盖旧备份）"""
    bak = path.with_name(path.name + ".bak")
    bak.write_bytes(path.read_bytes())
    return bak


def convert_file(path, to: str = "utf-8", bom: str = "keep",
                 backup: bool = True, dry: bool = False) -> dict:
    """转码单文件。永不崩溃。"""
    p = Path(path)
    d = detect(p)
    enc = d["encoding"]
    if enc in ("binary", "binary?", "unknown", "empty", "utf-16", "error"):
        return {"status": "skip", "from": enc, "note": d.get("note", "不处理")}
    if enc == "utf-8-sig":
        enc = "utf-8"
    if enc == to and bom == "keep":
        return {"status": "skip", "from": enc, "note": "已是目标编码"}
    if dry:
        return {"status": "dry", "from": enc, "note": f"将转换为 {to}"}
    with _file_lock:
        try:
            raw = read_bytes(p)
        except (OSError, PermissionError) as e:
            return {"status": "skip", "from": enc, "note": f"读取失败: {e.strerror or e}"}
        if raw.startswith(BOM_UTF8):
            raw = raw[len(BOM_UTF8):]
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            return {"status": "skip", "from": enc, "note": "解码失败"}
        note_extra = ""
        try:
            data = text.encode(to)
        except UnicodeEncodeError:
            data = text.encode(to, errors="replace")
            note_extra = "（含目标编码无法表示的字符，已替换为 ?）"
        if backup:
            try:
                _backup(p)
            except (OSError, PermissionError) as e:
                return {"status": "skip", "from": enc, "note": f"备份失败: {e.strerror or e}"}
        if bom == "add" or (to == "utf-8" and bom == "keep" and d["encoding"] == "utf-8-sig") or \
           (to == "utf-8" and bom == "keep" and d["bom"]):
            if not data.startswith(BOM_UTF8):
                data = BOM_UTF8 + data
        try:
            p.write_bytes(data)
        except (OSError, PermissionError) as e:
            return {"status": "skip", "from": enc, "note": f"写入失败: {e.strerror or e}"}
        return {"status": "ok", "from": enc, "note": f"{enc} → {to}{note_extra}"}


def fix_text(s: str) -> Optional[Tuple[str, str, float]]:
    """尝试修复双重编码乱码。长度 < 4 个非空字符不尝试（误报风险极高）。"""
    chars = [c for c in s if not c.isspace()]
    if len(chars) < 4:
        return None
    base = cjk_ratio(s)
    best = None
    for rev in ("gbk", "latin-1", "cp1252"):
        try:
            raw = s.encode(rev)
        except UnicodeEncodeError:
            continue
        try:
            rec = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if rec == s:
            continue
        gain = cjk_ratio(rec) - base
        if gain > 0.05 or (rev == "gbk" and base >= 0.05):
            if best is None or gain > best[2]:
                best = (rec, rev, gain if gain > 0 else 1.0)
    return best


def fix_file(path, backup: bool = True, dry: bool = False) -> dict:
    """修复文件中的双重编码乱码。永不崩溃。"""
    p = Path(path)
    d = detect(p)
    if d["encoding"] not in ("utf-8", "utf-8-sig"):
        return {"status": "skip", "from": d["encoding"], "note": d.get("note", "仅处理UTF-8乱码文本")}
    had_bom = d["encoding"] == "utf-8-sig"
    with _file_lock:
        try:
            raw = read_bytes(p)
        except (OSError, PermissionError) as e:
            return {"status": "skip", "from": d["encoding"], "note": f"读取失败: {e.strerror or e}"}
        body = raw[len(BOM_UTF8):] if raw.startswith(BOM_UTF8) else raw
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return {"status": "skip", "from": "utf-8", "note": "解码失败"}
        r = fix_text(text)
        if r is None:
            return {"status": "skip", "from": "utf-8", "note": "未发现可修复的乱码模式"}
        fixed, rev, gain = r
        sample = fixed[:24].replace("\n", " ").replace("\r", "")
        if dry:
            return {"status": "dry", "from": "utf-8", "note": f"预览: {sample}…（反推 {rev}）"}
        if backup:
            try:
                _backup(p)
            except (OSError, PermissionError) as e:
                return {"status": "skip", "from": "utf-8", "note": f"备份失败: {e.strerror or e}"}
        data = fixed.encode("utf-8")
        if had_bom:
            data = BOM_UTF8 + data
        try:
            p.write_bytes(data)
        except (OSError, PermissionError) as e:
            return {"status": "skip", "from": "utf-8", "note": f"写入失败: {e.strerror or e}"}
        return {"status": "ok", "from": "utf-8", "note": f"已修复（反推 {rev}）: {sample}…"}


def bom_file(path, mode: str, dry: bool = False, backup: bool = True) -> dict:
    """mode: add / strip。永不崩溃。backup: 写入前是否生成 .bak。"""
    p = Path(path)
    d = detect(p)
    if d["encoding"] not in ("utf-8", "utf-8-sig"):
        return {"status": "skip", "from": d["encoding"], "note": d.get("note", "仅处理UTF-8文件")}
    with _file_lock:
        try:
            raw = read_bytes(p)
        except (OSError, PermissionError) as e:
            return {"status": "skip", "from": d["encoding"], "note": f"读取失败: {e.strerror or e}"}
        has = raw.startswith(BOM_UTF8)
        if mode == "add":
            if has:
                return {"status": "skip", "from": "utf-8-sig", "note": "已有BOM"}
            if dry:
                return {"status": "dry", "from": "utf-8", "note": "将添加BOM"}
            if backup:
                try:
                    _backup(p)
                except (OSError, PermissionError) as e:
                    return {"status": "skip", "from": "utf-8", "note": f"备份失败: {e.strerror or e}"}
            try:
                p.write_bytes(BOM_UTF8 + raw)
            except (OSError, PermissionError) as e:
                return {"status": "skip", "from": "utf-8", "note": f"写入失败: {e.strerror or e}"}
            return {"status": "ok", "from": "utf-8", "note": "已添加BOM（PowerShell 5.1 需要）"}
        if mode == "strip":
            if not has:
                return {"status": "skip", "from": "utf-8", "note": "本来就没有BOM"}
            if dry:
                return {"status": "dry", "from": "utf-8-sig", "note": "将移除BOM"}
            if backup:
                try:
                    _backup(p)
                except (OSError, PermissionError) as e:
                    return {"status": "skip", "from": "utf-8-sig", "note": f"备份失败: {e.strerror or e}"}
            try:
                p.write_bytes(raw[len(BOM_UTF8):])
            except (OSError, PermissionError) as e:
                return {"status": "skip", "from": "utf-8-sig", "note": f"写入失败: {e.strerror or e}"}
            return {"status": "ok", "from": "utf-8-sig", "note": "已移除BOM"}
        return {"status": "skip", "from": d["encoding"], "note": "未知模式"}


def iter_files(paths, recursive=False, includes=None, only_text_ext=False):
    """展开路径为文件列表。自动排除 .bak 备份文件。"""
    includes = includes or []
    exts = {i.lower().lstrip("*.") for i in includes}
    out = []
    for path in paths:
        p = Path(path)
        if p.is_file():
            if not p.name.endswith(".bak"):
                out.append(p)
        elif p.is_dir():
            if not recursive:
                continue
            for root, dirs, names in os.walk(p):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for n in names:
                    if n.endswith(".bak"):
                        continue
                    f = Path(root) / n
                    if exts and f.suffix.lower().lstrip(".") not in exts:
                        continue
                    if only_text_ext and not exts and f.suffix.lower() not in TEXT_EXT:
                        continue
                    out.append(f)
    return out
