import os

import pytest

# app.main builds a Store at import time. Without this seam, importing it
# during test collection would try to open a real Firestore connection.
# Must be set before any test module imports app.main, so it lives at
# conftest module scope (executed once, at collection time) rather than in
# a fixture (which would run too late, after collection has already
# imported every test module).
os.environ["USE_FAKE_STORE"] = "1"


@pytest.fixture(autouse=True)
def restore_environ():
    """Snapshot and restore ``os.environ`` around every test.

    ``load_config`` mutates the process environment (GOOGLE_GENAI_USE_VERTEXAI,
    GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION) by design. Without this
    fixture those writes escape the test that made them and persist for the
    rest of the pytest session, so a test run in isolation and the same test
    run inside the full suite see different starting environments — and any
    later test that boots the app in-process observes whichever value the
    first ``load_config`` caller happened to write. This lives in conftest so
    every test module in the substrate inherits it.
    """
    snapshot = os.environ.copy()
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
