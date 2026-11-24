"""Run with:  python -m unittest discover tests -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edge.testcases import ALL_TESTS  # noqa: E402


class SystemTestCases(unittest.TestCase):
    pass


def _make(fn):
    def test(self):
        r = fn()
        self.assertTrue(r["passed"], f"{r['id']}: {r['actual']}")
    return test


for _fn in ALL_TESTS:
    setattr(SystemTestCases, f"test_{_fn.__name__}", _make(_fn))

if __name__ == "__main__":
    unittest.main(verbosity=2)
