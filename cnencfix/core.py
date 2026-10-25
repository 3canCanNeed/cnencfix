# -*- coding: utf-8 -*-
"""cnencfix.core —— 编码检测 / 转换 / 乱码修复 / BOM 处理（零依赖，仅标准库）"""
from __future__ import annotations

import os
from pathlib import Path

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
    """检测文本是否为乱码：latin1 风格签名字符密度 + 逆推验证。

    GBK 误读 UTF-8 产生的字符落在 CJK 区（不能用签名集），用逆推：把文本
    编回 latin-1/gbk 后如果能严格解码为 UTF-8 且中文占比上升，就是乱码。
    """
    chars = [c for c in s if not c.isspace()]
    if not chars:
        return 0.0
    latin1_hits = sum(1 for c in chars if c in _MOJIBAKE_CHARS) / len(chars)
    if latin1_hits >= 0.15:
        return latin1_hits
    r = fix_text(s)
    if r is not None:
        return 1.0  # 逆推成功 → 确认是乱码
    return latin1_hits


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
    # 1) UTF-8 严格解码 —— 通过即高置信
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
    # 2) GBK 严格解码 + 中文占比验证（GBK 几乎什么都能解，必须看内容）
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


def read_bytes(path: str | Path) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def detect(path: str | Path, sample: int = 65536) -> dict:
    p = Path(path)
    d = {"file": str(p)}
    with open(p, "rb") as f:
        b = f.read(sample)
    d.update(detect_bytes(b))
    d["size"] = p.stat().st_size
    return d


def _backup(path: Path) -> Path:
    bak = path.with_name(path.name + ".bak")
    i = 1
    while bak.exists():
        i += 1
        bak = path.with_name(f"{path.name}.bak{i}")
    bak.write_bytes(path.read_bytes())
    return bak


def convert_file(path: str | Path, to: str = "utf-8", bom: str = "keep",
                 backup: bool = True, dry: bool = False) -> dict:
    """转码单文件。bom: keep/add/strip。返回 {status, from, note}"""
    p = Path(path)
    d = detect(p)
    enc = d["encoding"]
    if enc in ("binary", "binary?", "unknown", "empty", "utf-16"):
        return {"status": "skip", "from": enc, "note": "不处理非文本/未知编码文件"}
    if enc == "utf-8-sig":
        enc = "utf-8"
    if enc == to and bom == "keep":
        return {"status": "skip", "from": enc, "note": "已是目标编码"}
    if dry:
        return {"status": "dry", "from": enc, "note": f"将转换为 {to}"}
    raw = read_bytes(p)
    if raw.startswith(BOM_UTF8):
        raw = raw[len(BOM_UTF8):]
    text = raw.decode(enc)
    if backup:
        _backup(p)
    data = text.encode(to)
    if bom == "add" or (to == "utf-8" and bom == "keep" and d["encoding"] == "utf-8-sig") or \
       (to == "utf-8" and bom == "keep" and d["bom"]):
        if not data.startswith(BOM_UTF8):
            data = BOM_UTF8 + data
    elif bom == "strip":
        pass
    p.write_bytes(data)
    return {"status": "ok", "from": enc, "note": f"{enc} → {to}"}


def fix_text(s: str) -> tuple[str, str, float] | None:
    """尝试修复双重编码乱码：返回 (修复后文本, 反推编码, 置信增益) 或 None。

    GBK 误读场景（如 MATLAB 输出）：乱码文本本身已全是 CJK 字符（cjk≈0.95），
    逆推后中文占比不变但字符完全不同。判据改为：逆推可严格 round-trip 且产
    物不同于原文（GBK 误读的 CJK 字符恰好构成合法 UTF-8 字节对，正常中文
    几乎不可能反向碰巧成立）。latin-1 风格（Java 日志）：乱码含大量 Âåæ 签
    名字符，逆推后中文占比大幅上升，用 gain>0.05 判据。
    """
    base = cjk_ratio(s)
    base_moji = mojibake_score.__wrapped__(s) if hasattr(mojibake_score, "__wrapped__") else 0.0
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
            continue  # 无变化
        gain = cjk_ratio(rec) - base
        # 判据：latin1 风格占比显著上升；或 GBK 严格 round-trip 且产物不同
        # （正常中文编码为 GBK 后几乎不可能恰好构成合法 UTF-8 序列）
        if gain > 0.05 or (rev == "gbk" and base >= 0.05):
            if best is None or gain > best[2]:
                best = (rec, rev, gain if gain > 0 else 1.0)
    return best


def fix_file(path: str | Path, backup: bool = True, dry: bool = False) -> dict:
    """修复文件中的双重编码乱码（仅在明显改善时写回）"""
    p = Path(path)
    d = detect(p)
    if d["encoding"] not in ("utf-8", "utf-8-sig"):
        return {"status": "skip", "from": d["encoding"], "note": "仅处理UTF-8乱码文本"}
    had_bom = d["encoding"] == "utf-8-sig"
    raw = read_bytes(p)
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
        _backup(p)
    data = fixed.encode("utf-8")
    if had_bom:
        data = BOM_UTF8 + data
    p.write_bytes(data)
    return {"status": "ok", "from": "utf-8", "note": f"已修复（反推 {rev}）: {sample}…"}


def bom_file(path: str | Path, mode: str, dry: bool = False) -> dict:
    """mode: add / strip。add 仅对 UTF-8 文本（无 BOM 时加上）；strip 移除 UTF-8 BOM。"""
    p = Path(path)
    d = detect(p)
    if d["encoding"] not in ("utf-8", "utf-8-sig"):
        return {"status": "skip", "from": d["encoding"], "note": "仅处理UTF-8文件"}
    raw = read_bytes(p)
    has = raw.startswith(BOM_UTF8)
    if mode == "add":
        if has:
            return {"status": "skip", "from": "utf-8-sig", "note": "已有BOM"}
        if dry:
            return {"status": "dry", "from": "utf-8", "note": "将添加BOM"}
        p.write_bytes(BOM_UTF8 + raw)
        return {"status": "ok", "from": "utf-8", "note": "已添加BOM（PowerShell 5.1 需要）"}
    if mode == "strip":
        if not has:
            return {"status": "skip", "from": "utf-8", "note": "本来就没有BOM"}
        if dry:
            return {"status": "dry", "from": "utf-8-sig", "note": "将移除BOM"}
        p.write_bytes(raw[len(BOM_UTF8):])
        return {"status": "ok", "from": "utf-8-sig", "note": "已移除BOM"}
    return {"status": "skip", "from": d["encoding"], "note": "未知模式"}


def iter_files(paths, recursive=False, includes=None, only_text_ext=False):
    """展开路径为文件列表（目录需 recursive 或单文件）"""
    includes = includes or []
    exts = {i.lower().lstrip("*.") for i in includes}
    out = []
    for path in paths:
        p = Path(path)
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            if not recursive:
                continue
            for root, dirs, names in os.walk(p):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for n in names:
                    f = Path(root) / n
                    if exts and f.suffix.lower().lstrip(".") not in exts:
                        continue
                    if only_text_ext and not exts and f.suffix.lower() not in TEXT_EXT:
                        continue
                    out.append(f)
    return out
