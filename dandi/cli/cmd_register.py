import click

from .command import (
    dandiset_path_option,
    instance_option,
    main,
    map_to_click_exceptions,
)
from ..consts import known_instances


@main.command()
@dandiset_path_option(
    help="Top directory (local) for the dandiset, where dandi will download "
    "(or update existing) dandiset.yaml upon successful registration.  If not "
    "specified, content for the file will be printed to the screen."
)
@click.option(
    "-n", "--name", help="Short name or title for the dandiset.", prompt="Name"
)
@click.option(
    "-D",
    "--description",
    help="Description of the dandiset - high level summary of the experiment "
    "and type(s) of data.",
    prompt="Description",
)
# &
# Development options:  Set DANDI_DEVEL for them to become available
#
# TODO: should always go to dandi for now
@instance_option()
@map_to_click_exceptions
def register(name, description, dandiset_path=None, dandi_instance="dandi"):
    """Register a new dandiset in the DANDI archive.

    This command provides only a minimal set of metadata. It is
    recommended to use Web UI to fill out other metadata fields for the
    dandiset
    """
    from ..register import register

    dandi_instance = known_instances[dandi_instance]
    output = register(dandi_instance, name, description, dandiset_path)
    if output is not None:
        print(output)
