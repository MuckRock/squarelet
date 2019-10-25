# Squarelet
from squarelet.core.utils import file_path


def test_file_path_normal():
    """File path just appends base and filename if under the limit"""
    assert file_path("base", None, "filename.ext") == "base/filename.ext"


def test_file_path_long():
    """File path truncates the file name if necessary"""
    file_name = "a" * 100 + ".ext"
    assert len(file_path("base", None, file_name)) == 92
