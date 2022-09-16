import os

from click.testing import CliRunner


def test_validate_bids_error(bids_error_examples):
    from ..cmd_validate import validate_bids

    expected_error = "File does not match any pattern known to BIDS.\n"

    broken_dataset = os.path.join(bids_error_examples, "invalid_pet001")
    r = CliRunner().invoke(validate_bids, [broken_dataset])
    # Does it break?
    assert r.exit_code == 1

    # Does it report the issue correctly?
    assert expected_error in r.output
