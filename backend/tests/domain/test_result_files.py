import pytest

from app.runner.files import write_csv


@pytest.mark.parametrize("filename", ["../escape.csv", "/absolute.csv"])
def test_result_writer_rejects_paths_outside_the_declared_directory(tmp_path, filename):
    with pytest.raises(ValueError, match="within the declared output directory"):
        write_csv(object(), filename, tmp_path / "results")
