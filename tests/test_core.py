# -*- coding: utf-8 -*-
"""核心逻辑测试：检测 / 转换 / 乱码修复 / BOM"""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cnencfix import core


class TestDetect(unittest.TestCase):
    def test_gbk(self):
        b = "中文测试：今天天气不错。ABC123\r\n".encode("gbk")
        d = core.detect_bytes(b)
        self.assertEqual(d["encoding"], "gbk")
        self.assertGreater(d["cjk"], 0.3)

    def test_utf8(self):
        b = "中文测试：今天天气不错。ABC123\r\n".encode("utf-8")
        d = core.detect_bytes(b)
        self.assertEqual(d["encoding"], "utf-8")

    def test_utf8_bom(self):
        b = core.BOM_UTF8 + "中文".encode("utf-8")
        d = core.detect_bytes(b)
        self.assertEqual(d["encoding"], "utf-8-sig")
        self.assertTrue(d["bom"])

    def test_utf16(self):
        b = "中文".encode("utf-16")
        d = core.detect_bytes(b)
        self.assertEqual(d["encoding"], "utf-16")

    def test_binary(self):
        d = core.detect_bytes(b"\x00\x01\x02\x03\xff\xfe" * 10)
        self.assertEqual(d["encoding"], "binary")

    def test_empty(self):
        self.assertEqual(core.detect_bytes(b"")["encoding"], "empty")

    def test_pure_ascii_is_utf8(self):
        d = core.detect_bytes(b"hello world\nfoo bar\n")
        self.assertEqual(d["encoding"], "utf-8")

    def test_gbk_not_misdetected_as_utf8(self):
        # 关键判别：GBK 中文文本绝不能被误判为 UTF-8
        b = ("电力电子技术课程设计" * 20).encode("gbk")
        self.assertEqual(core.detect_bytes(b)["encoding"], "gbk")

    def test_mojibake_flagged(self):
        # UTF-8 字节被 GBK 误读后存回 UTF-8 的形态（CJK 区字符 + 逆推可恢复）
        moji = "无法关闭模型".encode("utf-8").decode("gbk")
        d = core.detect_bytes(moji.encode("utf-8"))
        self.assertEqual(d["encoding"], "utf-8")
        self.assertGreaterEqual(d["moji"], 0.5)


class TestConvert(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_gbk_to_utf8(self):
        f = self.dir / "log.txt"
        f.write_bytes("中文警告：无法关闭模型".encode("gbk"))
        r = core.convert_file(f, to="utf-8")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(f.read_bytes().decode("utf-8"), "中文警告：无法关闭模型")
        self.assertTrue(f.with_name("log.txt.bak").exists())  # 备份生成

    def test_utf8_to_gbk_roundtrip(self):
        f = self.dir / "a.txt"
        text = "转速 n = 1500 r/min，电枢电流 30 A"
        f.write_bytes(text.encode("utf-8"))
        core.convert_file(f, to="gbk", backup=False)
        self.assertEqual(f.read_bytes().decode("gbk"), text)
        core.convert_file(f, to="utf-8", backup=False)
        self.assertEqual(f.read_bytes().decode("utf-8"), text)

    def test_bom_keep_add_strip(self):
        f = self.dir / "b.txt"
        f.write_bytes(core.BOM_UTF8 + "中文".encode("utf-8"))
        # utf-8-sig → utf-8 且 keep → 保留 BOM
        core.convert_file(f, to="utf-8", bom="keep", backup=False)
        self.assertTrue(f.read_bytes().startswith(core.BOM_UTF8))
        # strip → 去掉
        core.convert_file(f, to="utf-8", bom="strip", backup=False)
        self.assertFalse(f.read_bytes().startswith(core.BOM_UTF8))
        # add → 加回
        core.convert_file(f, to="utf-8", bom="add", backup=False)
        self.assertTrue(f.read_bytes().startswith(core.BOM_UTF8))

    def test_crlf_preserved(self):
        f = self.dir / "c.txt"
        f.write_bytes("第一行\r\n第二行\r\n".encode("gbk"))
        core.convert_file(f, to="utf-8", backup=False)
        self.assertIn(b"\r\n", f.read_bytes())

    def test_skip_binary(self):
        f = self.dir / "d.bin"
        f.write_bytes(b"\x00\x01\x02")
        r = core.convert_file(f, to="utf-8")
        self.assertEqual(r["status"], "skip")

    def test_dry_run_no_write(self):
        f = self.dir / "e.txt"
        original = "中文".encode("gbk")
        f.write_bytes(original)
        r = core.convert_file(f, to="utf-8", dry=True)
        self.assertEqual(r["status"], "dry")
        self.assertEqual(f.read_bytes(), original)


class TestFix(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fix_gbk_mojibake(self):
        # 真实场景：一个 UTF-8 文件被程序以 GBK 打开再存回 UTF-8（无损、可逆）
        correct = "无法关闭模型，文档可能已损坏"
        moji_text = correct.encode("utf-8").decode("gbk")  # UTF-8 字节被 GBK 误读
        f = self.dir / "moji.txt"
        f.write_bytes(moji_text.encode("utf-8"))            # 再存为 UTF-8
        r = core.fix_file(f)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(f.read_bytes().decode("utf-8"), correct)
        self.assertTrue(f.with_name("moji.txt.bak").exists())

    def test_fix_short_mixed(self):
        # 混合中英但 UTF-8 字节恰为合法 GBK 序列的短文本
        correct = "Hello 世界"
        moji_text = correct.encode("utf-8").decode("gbk")
        f = self.dir / "moji2.txt"
        f.write_bytes(moji_text.encode("utf-8"))
        r = core.fix_file(f)
        self.assertEqual(r["status"], "ok")

    def test_no_false_fix(self):
        # 正常中文不能被“修复”破坏
        f = self.dir / "good.txt"
        f.write_bytes("这是完全正常的中文文本，没有任何乱码。".encode("utf-8"))
        r = core.fix_file(f)
        self.assertEqual(r["status"], "skip")
        self.assertEqual(f.read_bytes().decode("utf-8"), "这是完全正常的中文文本，没有任何乱码。")


class TestBom(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_and_strip(self):
        f = self.dir / "s.ps1"
        f.write_bytes("$s = '中文路径'\n".encode("utf-8"))
        r = core.bom_file(f, "add")
        self.assertEqual(r["status"], "ok")
        self.assertTrue(f.read_bytes().startswith(core.BOM_UTF8))
        # 再加 → skip
        self.assertEqual(core.bom_file(f, "add")["status"], "skip")
        # 去 → 回到无 BOM
        core.bom_file(f, "strip")
        self.assertFalse(f.read_bytes().startswith(core.BOM_UTF8))

    def test_gbk_notouched(self):
        f = self.dir / "g.txt"
        f.write_bytes("中文".encode("gbk"))
        self.assertEqual(core.bom_file(f, "add")["status"], "skip")


class TestIterFiles(unittest.TestCase):
    def test_recursive_with_skipdirs(self):
        with TemporaryDirectory() as t:
            t = Path(t)
            (t / "a.txt").write_text("x")
            (t / ".git").mkdir()
            (t / ".git" / "b.txt").write_text("x")
            files = core.iter_files([t], recursive=True)
            names = [f.name for f in files]
            self.assertIn("a.txt", names)
            self.assertNotIn("b.txt", names)

    def test_include_filter(self):
        with TemporaryDirectory() as t:
            t = Path(t)
            (t / "a.log").write_text("x")
            (t / "b.csv").write_text("x")
            files = core.iter_files([t], recursive=True, includes=["log"])
            self.assertEqual([f.name for f in files], ["a.log"])


if __name__ == "__main__":
    unittest.main()
