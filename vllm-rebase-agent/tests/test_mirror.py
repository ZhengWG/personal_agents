import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from pipeline import tasks


class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = pathlib.Path(self.tmp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        (self.repo / "cmake").mkdir()
        (self.repo / "cmake/deps.cmake").write_text("# fixture\n")
        (self.repo / "CMakeLists.txt").write_text("$ENV{TRITON_KERNELS_SRC_DIR}\n")
        (self.repo / "pyproject.toml").write_text("")
        self.script = self.repo / "tools/mirror.py"
        self.script.parent.mkdir()
        self.script.write_text("raise RuntimeError('stale checkout parser')\n")
        self.commit()
        self.old = self.git("rev-parse", "HEAD")
        self.cfg = {
            "repo": str(self.repo),
            "ant_remote": "ant",
            "delta_source": "ant/public_tracker",
            "oss_mirror": {"script": "tools/mirror.py", "refs": ["public_tracker_daily"],
                           "oss_prefix": "oss://unused/test"},
        }

    def git(self, *args):
        return subprocess.check_output(
            ["git", *args], cwd=self.repo, text=True, stderr=subprocess.STDOUT).strip()

    def commit(self):
        self.git("add", ".")
        self.git("-c", "core.hooksPath=/dev/null", "commit", "-qm", "fixture")

    def publish_parser(self, manifest):
        self.script.write_text(
            "import sys\nif sys.argv[1] == 'manifest':\n"
            + "\n".join("    " + line for line in manifest.splitlines())
            + "\nelse:\n    print('[ok ] triton_kernels')\n")
        self.commit()
        sha = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/remotes/ant/public_tracker", sha)
        self.git("update-ref", "refs/remotes/ant/public_tracker_daily", self.old)
        self.git("checkout", "-q", self.old)
        return sha

    def test_uses_published_parser_without_changing_checkout(self):
        sha = self.publish_parser("print('triton_kernels\\ttriton.tar.gz\\turl\\tTRITON_KERNELS_SRC_DIR')")
        result = tasks.mirror_oss_deps(self.cfg)
        self.assertTrue(result["done"], result)
        self.assertEqual(result["script_sha"], sha)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.old)
        self.assertIn("stale checkout parser", self.script.read_text())
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_rejects_missing_hook_even_when_sync_reports_ok(self):
        self.publish_parser("print('# empty manifest')")
        result = tasks.mirror_oss_deps(self.cfg)
        self.assertFalse(result["done"])
        self.assertIn("TRITON_KERNELS_SRC_DIR", result["reason"])

    def test_rejects_failed_manifest_even_with_complete_output(self):
        self.publish_parser("print('dep\\tarchive\\turl\\tTRITON_KERNELS_SRC_DIR')\nsys.exit(1)")
        self.assertFalse(tasks.mirror_oss_deps(self.cfg)["done"])

    def test_does_not_fall_back_to_checkout_when_source_missing(self):
        self.git("update-ref", "refs/remotes/ant/public_tracker_daily", self.old)
        self.assertFalse(tasks.mirror_oss_deps(self.cfg)["done"])

    def test_push_waits_for_candidate_dependencies_and_blocks_on_failure(self):
        self.cfg["worktree"] = str(self.repo)
        task = {"push": {"enabled": True, "after_resolve": True,
                         "ref": "public_tracker_daily"}}
        for resolved in (False, True):
            for ready in (False, True):
                with self.subTest(resolved=resolved, ready=ready):
                    events = []

                    def mirror(config, *, refs, script_ref):
                        self.assertEqual(refs, [self.old])
                        self.assertEqual(script_ref, self.old)
                        events.append("mirror")
                        return {"done": ready, "reason": "fixture"}

                    def git(args, *a, **kw):
                        self.assertEqual(args[0], "push")
                        self.assertEqual(args[-1], self.old + ":refs/heads/public_tracker_daily")
                        events.append("push")
                        return 0, "ok"

                    entry = {"status": "clean", "verified": True}
                    with mock.patch.object(tasks, "mirror_oss_deps", mirror), \
                         mock.patch.object(tasks.g, "git", git), \
                         mock.patch.object(tasks.g, "rev", return_value=self.old):
                        if resolved:
                            session = {"state": "finished", "head": self.old, "entry": entry}
                            result = tasks.push_resolved(self.cfg, task, session, {}, True)
                        else:
                            tasks.maybe_push(entry, task, self.cfg, {}, str(self.repo), True)
                            result = entry["push"]
                    self.assertEqual(result["done"], ready)
                    self.assertEqual(events, ["mirror", "push"] if ready else ["mirror"])


if __name__ == "__main__":
    unittest.main()
