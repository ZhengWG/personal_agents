"""Sentence punctuation must not become part of an auto-promoted repo name.

`REPO_RE` allows `.` and `-` inside owner/repo, so a link that ends a sentence
(`github.com/vllm-project/vllm.`) matches `vllm-project/vllm.`. That string is
not the tracked repo, gets promoted, and then `repo:vllm-project/vllm.` makes
GitHub reject the whole PR-search chunk.
"""

import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from pipeline import discover, fetch


class CleanRepoMentionTests(unittest.TestCase):
    def test_strips_sentence_tail_and_git_suffix(self):
        cases = {
            "vllm-project/vllm.": "vllm-project/vllm",
            "vllm-project/vllm.-": "vllm-project/vllm",
            "vllm-project/vllm-": "vllm-project/vllm",
            "vllm-project/vllm.git": "vllm-project/vllm",
            "vllm-project/vllm.git.": "vllm-project/vllm",
            "vllm-project/vllm.git-": "vllm-project/vllm",
            "org/my.repo": "org/my.repo",
            "org/my.repo.": "org/my.repo",
            "org/name-with-hyphen": "org/name-with-hyphen",
            "owner/": "",
            ".../....": "",
        }
        for raw, want in cases.items():
            self.assertEqual(fetch.clean_repo_mention(raw), want, raw)

    def test_regex_still_captures_the_trailing_period(self):
        blob = "See https://github.com/vllm-project/vllm. Next sentence."
        self.assertEqual(fetch.REPO_RE.findall(blob), ["vllm-project/vllm."])


class TallyAndPromoteTests(unittest.TestCase):
    def test_dotted_alias_of_tracked_repo_is_not_a_candidate(self):
        cfg = {
            "tracked": [{"repo": "vllm-project/vllm", "prs": True, "releases": True}],
            "candidates": {},
            "ignore": [],
            "discovery": {"promote_runs": 3, "promote_items": 2},
        }
        tracked = {"vllm-project/vllm"}
        blob = (
            "Release notes: https://github.com/vllm-project/vllm. "
            "Again https://github.com/vllm-project/vllm. "
            "Clone https://github.com/vllm-project/vllm.git."
        )
        promoted = fetch.tally_and_promote(cfg, blob, tracked, "2026-11-06")
        self.assertEqual(promoted, [])
        self.assertEqual(cfg["candidates"], {})
        self.assertEqual([t["repo"] for t in cfg["tracked"]], ["vllm-project/vllm"])

    def test_new_repo_is_promoted_under_the_cleaned_name(self):
        cfg = {
            "tracked": [],
            "candidates": {},
            "ignore": [],
            "discovery": {"promote_runs": 3, "promote_items": 2},
        }
        blob = (
            "https://github.com/org/new-engine. "
            "https://github.com/org/new-engine-"
        )
        promoted = fetch.tally_and_promote(cfg, blob, set(), "2026-11-06")
        self.assertEqual(promoted, ["org/new-engine"])
        self.assertEqual(cfg["tracked"][0]["repo"], "org/new-engine")
        self.assertNotIn("org/new-engine.", cfg["candidates"])
        self.assertNotIn("org/new-engine-", cfg["candidates"])


class LoadAwesomeTests(unittest.TestCase):
    def test_strips_period_and_git_suffix(self):
        cfg = {"discovery": {"awesome_lists": ["xlite-dev/Awesome-LLM-Inference"]}}
        md = (
            "https://github.com/vllm-project/vllm.\n"
            "https://github.com/org/foo.git\n"
            "https://github.com/org/bar.git.\n"
        )
        with mock.patch.object(fetch, "http_get", return_value=md.encode()):
            names = fetch.load_awesome(cfg)
        self.assertEqual(names, {"vllm-project/vllm", "org/foo", "org/bar"})


class AwesomeNewTests(unittest.TestCase):
    def test_snapshot_uses_cleaned_names(self):
        cfg = {"discovery": {"awesome_lists": ["some/list"]}}
        state = {"awesome_snapshots": {"some/list": {"repos": ["vllm-project/vllm"]}}}
        md = (
            "https://github.com/vllm-project/vllm.\n"
            "https://github.com/org/brand-new.git.\n"
        )
        with mock.patch.object(discover, "http_get", return_value=md.encode()):
            out = discover.fetch_awesome_new(
                cfg, state, set(), set(), record=True)
        self.assertEqual([x["repo"] for x in out], ["org/brand-new"])
        self.assertEqual(
            state["awesome_snapshots"]["some/list"]["repos"],
            ["org/brand-new", "vllm-project/vllm"],
        )


if __name__ == "__main__":
    unittest.main()
