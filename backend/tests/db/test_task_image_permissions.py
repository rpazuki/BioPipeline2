"""Verify that restrictive deployment checkouts produce usable non-root task images."""

import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def private_checkout_context(tmp_path_factory):
    if shutil.which("docker") is None:
        pytest.skip("Docker is not available")
    probe = subprocess.run(["docker", "info"], capture_output=True, timeout=15, check=False)
    if probe.returncode:
        pytest.skip("Docker is not available")
    context = tmp_path_factory.mktemp("private-image-context")
    runner = context / "backend/app/runner"
    shutil.copytree(
        ROOT / "backend/app/runner", runner, ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copyfile(ROOT / "deploy/images/task/Dockerfile", context / "Dockerfile")
    for path in context.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    return context


@pytest.fixture(scope="module")
def private_checkout_image(private_checkout_context):
    image = f"biopipeline2/task-permission-test:{uuid.uuid4().hex}"
    try:
        built = subprocess.run(
            ["docker", "build", "--tag", image, str(private_checkout_context)],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        assert built.returncode == 0, built.stdout + built.stderr
        yield image
    finally:
        subprocess.run(
            ["docker", "image", "rm", "--force", image],
            capture_output=True,
            timeout=30,
            check=False,
        )


@pytest.mark.parametrize("run_as", [None, "987:986", "4242:4343"])
def test_image_runner_is_readable_from_private_checkout(private_checkout_image, run_as):
    command = ["docker", "run", "--rm", "--read-only", "--network", "none"]
    if run_as:
        command += ["--user", run_as]
    command += [
        private_checkout_image,
        "python",
        "-c",
        "from app.runner import main, files; from pathlib import Path; "
        "assert files.as_path('input.csv') == Path('input.csv'); "
        "assert all(p.stat().st_mode & 0o444 == 0o444 and not p.stat().st_mode & 0o022 "
        "for p in Path(files.__file__).parent.rglob('*.py'))",
    ]
    checked = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    assert checked.returncode == 0, checked.stdout + checked.stderr


def test_image_build_refuses_an_unreadable_new_runner_module(private_checkout_context, tmp_path):
    context = tmp_path / "broken-context"
    shutil.copytree(private_checkout_context, context)
    dockerfile = context / "Dockerfile"
    content = dockerfile.read_text()
    source = "/usr/local/lib/python3.12/site-packages/app/runner/unreadable_probe.py"
    content = content.replace(
        "\nUSER task\n",
        f"\nRUN touch {source} && chmod 600 {source}\nUSER task\n",
        1,
    )
    dockerfile.write_text(content)
    built = subprocess.run(
        ["docker", "build", str(context)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    output = built.stdout + built.stderr
    assert built.returncode != 0, output
    assert "AssertionError: Runner source is not readable by all task users" in output, output
