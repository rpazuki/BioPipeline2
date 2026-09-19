"""What is installed, and whether that is a fact anyone can reproduce."""

from __future__ import annotations

import pytest

from app.domain.packaging import (
    Package,
    SpecifierRejected,
    check_specifier,
    describe_editables,
    digest_of,
    is_reproducible,
    read_inventory,
)

PIP_OUTPUT = [
    {"name": "pandas", "version": "2.2.1"},
    {"name": "numpy", "version": "1.26.4"},
    # What the real install history has, and what no digest can capture.
    {"name": "labUtils", "version": "0.4.0", "editable_project_location": "/srv/labUtils"},
]


def test_pips_own_output_is_what_is_read():
    packages = read_inventory(PIP_OUTPUT)
    assert [package.name for package in packages] == ["labUtils", "numpy", "pandas"]
    assert packages[0].editable_path == "/srv/labUtils"


def test_the_digest_is_over_the_resolved_set_not_the_specifier():
    """`pip install pandas` means different things on different days."""
    first = digest_of(read_inventory([{"name": "pandas", "version": "2.2.1"}]))
    second = digest_of(read_inventory([{"name": "pandas", "version": "2.2.2"}]))
    assert first != second
    assert first.startswith("sha256:")


def test_order_does_not_change_the_digest():
    forward = digest_of(read_inventory(PIP_OUTPUT))
    backward = digest_of(read_inventory(list(reversed(PIP_OUTPUT))))
    assert forward == backward


def test_an_editable_install_changes_the_identity():
    """Honest rather than useful: it makes the two differ, and claims nothing
    about the contents of the path being the same twice."""
    plain = digest_of([Package(name="labUtils", version="0.4.0")])
    editable = digest_of([Package(name="labUtils", version="0.4.0", editable_path="/srv/l")])
    assert plain != editable


def test_an_editable_install_makes_a_set_unreproducible():
    assert is_reproducible(read_inventory(PIP_OUTPUT[:2]))
    assert not is_reproducible(read_inventory(PIP_OUTPUT))


def test_the_reason_names_the_package_and_the_path():
    note = describe_editables(read_inventory(PIP_OUTPUT))
    assert note is not None
    assert "labUtils (/srv/labUtils)" in note
    assert "cannot be reproduced" in note


def test_nothing_to_say_when_everything_is_reproducible():
    assert describe_editables(read_inventory(PIP_OUTPUT[:2])) is None


@pytest.mark.parametrize(
    "specifier",
    ["pandas", "pandas==2.2.1", "scikit-learn>=1.4", "pandas[performance]", "labUtils~=0.4"],
)
def test_the_specifiers_an_admin_actually_types(specifier):
    assert check_specifier(f"  {specifier} ") == specifier


@pytest.mark.parametrize(
    "specifier",
    [
        "--index-url http://elsewhere/simple pandas",
        "-e /srv/labUtils",
        "pandas; python_version < '3'",
        "pandas && rm -rf /",
        "https://example.org/thing.whl",
        "",
    ],
)
def test_anything_that_is_not_plainly_a_package_is_refused(specifier):
    """This runs as an administrator on the machine that runs everybody's
    work. A flag slipped into the box would be an install nobody reviewed."""
    with pytest.raises(SpecifierRejected):
        check_specifier(specifier)
