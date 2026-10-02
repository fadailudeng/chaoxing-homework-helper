"""清理缓存的安全回归测试（不联网、不真删）。

这一组测试守的是一句话：**清理缓存只能清掉垃圾，不许碰登录态和已扫出来的数据。**

做法：把清理目标和保护清单原样跑一遍 `_guard()`（它只做判断、不删文件），
确认「该删的能过、不该删的一律被拒」。用一个临时目录假造出全部文件和目录，
所以跑测试不会动到真实数据 —— 想验证真删的行为请手动跑 `src/cleanup_cli.py`。

跑法：python tests/test_cleanup.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import cleanup  # noqa: E402
import config  # noqa: E402


class TestGuardWhitelist(unittest.TestCase):
    """_guard：白名单外的路径必须被拒。"""

    def test_whitelisted_targets_pass(self):
        for t in cleanup.clean_targets():
            with self.subTest(target=t.path.name):
                cleanup._guard(t.path)   # 不抛异常 = 通过

    def test_data_dir_itself_rejected(self):
        with self.assertRaises(ValueError):
            cleanup._guard(config.DATA_DIR)

    def test_root_rejected(self):
        with self.assertRaises(ValueError):
            cleanup._guard(config.ROOT)

    def test_debug_dir_itself_rejected(self):
        # debug 整个目录不在白名单里（只能逐个文件/子目录清）
        with self.assertRaises(ValueError):
            cleanup._guard(config.DEBUG_DIR)

    def test_wildcard_would_be_rejected(self):
        with self.assertRaises(ValueError):
            cleanup._guard(config.ROOT / "*")

    def test_traversal_rejected(self):
        # 想用 data/../data 绕过去 —— resolved() 之后和白名单对不上
        sneaky = config.WEBVIEW_PROFILE_DIR / ".." / "browser_profile"
        with self.assertRaises(ValueError):
            cleanup._guard(sneaky)


class TestProtectedNeverInWhitelist(unittest.TestCase):
    """保护清单里的东西，一个都不许出现在清理白名单里。"""

    def test_no_overlap(self):
        allowed = {t.path.resolve() for t in cleanup.clean_targets()}
        for path, label in cleanup._protected():
            with self.subTest(protected=label):
                self.assertNotIn(path.resolve(), allowed,
                                 f"{label} 不应出现在清理白名单里")

    def test_nothing_under_protected(self):
        """白名单目标不能落在任何受保护路径**内部**。"""
        for t in cleanup.clean_targets():
            resolved = t.path.resolve()
            for prot, label in cleanup._protected():
                with self.subTest(target=t.path.name, protected=label):
                    prot_r = prot.resolve()
                    self.assertNotEqual(resolved, prot_r)
                    self.assertNotIn(prot_r, resolved.parents,
                                     f"{t.path} 落在「{label}」里了")

    def test_homework_backup_is_glob_protected(self):
        """debug 里的数据备份（homework_backup_*.json）必须删不掉。"""
        sample = config.DEBUG_DIR / "homework_backup_155808.json"
        self.assertIsNotNone(cleanup._glob_protected(sample))

    def test_normal_debug_png_not_glob_protected(self):
        sample = config.DEBUG_DIR / "ui_preview.png"
        self.assertIsNone(cleanup._glob_protected(sample))

    def test_backup_not_in_whitelist(self):
        names = {t.path.name for t in cleanup.clean_targets()}
        self.assertFalse([n for n in names if n.startswith("homework_backup")])


class TestProtectedFingerprintInTempDir(unittest.TestCase):
    """真的用临时目录跑一次 run()，确认保护内容一个字节都没变。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # 假造目录结构
        (self.root / "data").mkdir()
        (self.root / "debug").mkdir()
        (self.root / "web").mkdir()
        (self.root / "src").mkdir()
        (self.root / "assets").mkdir()
        # 保护内容
        (self.root / "data" / "browser_profile").mkdir()
        (self.root / "data" / "browser_profile" / "Cookies").write_text("secret", encoding="utf-8")
        (self.root / "data" / "login_state.json").write_text('{"c":1}', encoding="utf-8")
        (self.root / "data" / "homework.json").write_text('{"courses":[]}', encoding="utf-8")
        (self.root / "data" / "tasks.json").write_text("{}", encoding="utf-8")
        (self.root / "data" / "题目").mkdir()
        (self.root / "data" / "题目" / "a.md").write_text("# 题", encoding="utf-8")
        # 待清理的垃圾
        (self.root / "data" / "ui_profile").mkdir()
        (self.root / "data" / "ui_profile" / "blob").write_bytes(b"x" * 4096)
        (self.root / "debug" / "preview_profile").mkdir()
        (self.root / "debug" / "preview_profile" / "f").write_bytes(b"y" * 1024)
        (self.root / "debug" / "homework_backup_155808.json").write_text("{}", encoding="utf-8")

        # 把 cleanup/config 的路径指到临时目录
        self._saved = {
            "ROOT": config.ROOT,
            "DATA_DIR": config.DATA_DIR,
            "DEBUG_DIR": config.DEBUG_DIR,
            "WEBVIEW_PROFILE_DIR": config.WEBVIEW_PROFILE_DIR,
            "BROWSER_PROFILE_DIR": config.BROWSER_PROFILE_DIR,
            "STATE_JSON": config.STATE_JSON,
            "RESULT_JSON": config.RESULT_JSON,
            "TASKS_JSON": config.TASKS_JSON,
            "TASKS_DIR": config.TASKS_DIR,
            "COURSES_CACHE": config.COURSES_CACHE,
            "SELECTION_JSON": config.SELECTION_JSON,
            "SCAN_LOG": config.SCAN_LOG,
            "WEB_DIR": config.WEB_DIR,
            "RAW_HTML_DIR": config.RAW_HTML_DIR,
        }
        r = self.root
        config.ROOT = r
        config.DATA_DIR = r / "data"
        config.DEBUG_DIR = r / "debug"
        config.WEBVIEW_PROFILE_DIR = r / "data" / "ui_profile"
        config.BROWSER_PROFILE_DIR = r / "data" / "browser_profile"
        config.STATE_JSON = r / "data" / "login_state.json"
        config.RESULT_JSON = r / "data" / "homework.json"
        config.TASKS_JSON = r / "data" / "tasks.json"
        config.TASKS_DIR = r / "data" / "题目"
        config.COURSES_CACHE = r / "data" / "courses_cache.json"
        config.SELECTION_JSON = r / "data" / "selection.json"
        config.SCAN_LOG = r / "data" / "scan_log.txt"
        config.WEB_DIR = r / "web"
        config.RAW_HTML_DIR = r / "debug" / "raw_html"

    def tearDown(self):
        for key, val in self._saved.items():
            setattr(config, key, val)
        self._tmp.cleanup()

    def test_run_deletes_cache_keeps_protected(self):
        result = cleanup.run(include_optional=False)

        # 该删的删了
        self.assertFalse((self.root / "data" / "ui_profile").exists())
        self.assertFalse((self.root / "debug" / "preview_profile").exists())
        # 用字节数断言：样本只有几 KB，_mb() 会四舍五入成 0.0
        self.assertEqual(len(result["removed"]), 2)
        self.assertGreater(sum(r["files"] for r in result["removed"]), 0)

        # 保护内容原封不动
        self.assertTrue((self.root / "data" / "browser_profile" / "Cookies").exists())
        self.assertEqual(
            (self.root / "data" / "browser_profile" / "Cookies").read_text(encoding="utf-8"),
            "secret",
        )
        self.assertTrue((self.root / "data" / "login_state.json").exists())
        self.assertTrue((self.root / "data" / "homework.json").exists())
        self.assertTrue((self.root / "data" / "tasks.json").exists())
        self.assertTrue((self.root / "data" / "题目" / "a.md").exists())

        # 数据备份也必须还在
        self.assertTrue((self.root / "debug" / "homework_backup_155808.json").exists())

        self.assertTrue(result["protected_ok"])
        self.assertEqual([e for e in result["errors"]], [])

    def test_survey_lists_protected(self):
        info = cleanup.survey()
        kinds = {p["path"] for p in info["items"]}
        self.assertTrue(any("ui_profile" in k for k in kinds))
        prot = {p["path"] for p in info["protected"]}
        self.assertTrue(any("browser_profile" in p for p in prot))
        self.assertTrue(any("homework.json" in p for p in prot))

    def test_optional_excluded_by_default(self):
        """default（安全档）不该碰 raw_html / 截图。"""
        (self.root / "debug" / "raw_html").mkdir()
        (self.root / "debug" / "raw_html" / "a.html").write_text("x", encoding="utf-8")
        (self.root / "debug" / "ui_preview.png").write_bytes(b"z" * 512)

        cleanup.run(include_optional=False)
        self.assertTrue((self.root / "debug" / "raw_html" / "a.html").exists())
        self.assertTrue((self.root / "debug" / "ui_preview.png").exists())

    def test_optional_included_when_asked(self):
        (self.root / "debug" / "raw_html").mkdir()
        (self.root / "debug" / "raw_html" / "a.html").write_text("x", encoding="utf-8")

        cleanup.run(include_optional=True)
        self.assertFalse((self.root / "debug" / "raw_html").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
