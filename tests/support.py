"""What more than one test file needs and none of them should own.

A database made for one test used to be a temporary directory nobody removed
and a connection nobody closed, five files over, each with its own copy of the
same line. One helper, and the case cleans up after itself.
"""

import tempfile
import unittest
from pathlib import Path

from weave.db import Database


def scratch_db(case: unittest.TestCase) -> Database:
    """A fresh database in a directory of its own, both gone when the test
    ends whichever way it ends."""
    tmp = tempfile.TemporaryDirectory(prefix="weave-test-")
    case.addCleanup(tmp.cleanup)
    db = Database(Path(tmp.name) / "weave.db")
    case.addCleanup(db.close)
    return db
