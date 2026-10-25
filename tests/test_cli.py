# -*- coding: utf-8 -*-
"""CLI 端到端测试：不弹子进程，直接调 main()"""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cnencfix.cli import main


def run(*argv) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(list(argv))
    return buf.getvalue() + f"\n[RC={rc}]"


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan_reports(self):
        f = self.dir / "mat.log"
        f.write_bytes("警告: 无法关闭模型".encode("gbk"))
        out = run("scan", str(f))
        self.assertIn("gbk", out)
        self.assertIn("[RC=0]", out)

    def test_conv_end_to_end(self):
        f = self.dir / "mat.log"
        f.write_bytes("警告: 无法关闭模型".encode("gbk"))
        out = run("conv", str(f), "--to", "utf8", "--no-backup")
        self.assertIn("OK", out)
        self.assertEqual(f.read_bytes().decode("utf-8"), "警告: 无法关闭模型")

    def test_conv_dry_run(self):
        f = self.dir / "mat.log"
        original = "警告".encode("gbk")
        f.write_bytes(original)
        out = run("conv", str(f), "--to", "utf8", "--dry-run")
        self.assertIn("预览", out)
        self.assertEqual(f.read_bytes(), original)  # 未写入

    def test_fix_end_to_end(self):
        correct = "无法关闭模型，文档可能已损坏"
        moji_text = correct.encode("utf-8").decode("gbk")
        f = self.dir / "bad.txt"
        f.write_bytes(moji_text.encode("utf-8"))
        out = run("fix", str(f))
        self.assertIn("修复", out)
        self.assertEqual(f.read_bytes().decode("utf-8"), correct)

    def test_bom_ps1(self):
        f = self.dir / "run.ps1"
        f.write_bytes("$p = 'D:\\中文路径\\文件.docx'\n".encode("utf-8"))
        out = run("bom", str(self.dir), "-r", "--auto-ps1")
        self.assertIn("BOM", out)
        self.assertTrue(f.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_recursive_scan(self):
        sub = self.dir / "logs"
        sub.mkdir()
        (sub / "a.log").write_bytes("中文".encode("gbk"))
        out = run("scan", str(self.dir), "-r", "--include", "log")
        self.assertIn("gbk", out)

    def test_no_args_errors(self):
        """无子命令 → argparse 报错 → SystemExit(2)，不是我们的 rc"""
        with self.assertRaises(SystemExit) as cm:
            main([])
        self.assertEqual(cm.exception.code, 2)  # argparse required subcommand


if __name__ == "__main__":
    unittest.main()
