"""Toolchain smoke test: proves the package installs and pytest runs.

Replaced by real tests in Phase 1.
"""

import sia


def test_package_is_importable() -> None:
    assert sia.__version__ == "0.1.0"
