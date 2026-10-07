"""Every package imports, which locks the public module layout."""

from __future__ import annotations

import clearbed
from clearbed import agent, api, features, ingest, ml, rag
from clearbed import eval as eval_pkg
from clearbed import logging as log_mod


def test_version() -> None:
    assert clearbed.__version__ == "0.1.0"


def test_packages_import() -> None:
    assert ingest.__doc__
    assert features.__doc__
    assert ml.__doc__
    assert rag.__doc__
    assert agent.__doc__
    assert api.__doc__
    assert eval_pkg.__doc__
    assert log_mod.__doc__
