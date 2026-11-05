"""Setup shared by all tests."""

import pytest

from cja import generator


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--network",
        action="store_true",
        help="run the tests that need internet access (marked with network)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--network"):
        return
    skip = pytest.mark.skip(reason="needs internet access, run with --network")
    for item in items:
        if item.get_closest_marker("network") is not None:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _unknown_standard_default(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Make -std flags independent of the compiler running the tests.

    Compile features only build on the compiler's default standard when cja
    could detect it, so tests act as if that failed, unless they're marked
    with compiler_standard_default.
    """
    if request.node.get_closest_marker("compiler_standard_default") is None:
        monkeypatch.setattr(generator, "_infer_standard_default", lambda *_: None)
