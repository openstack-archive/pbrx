# Copyright 2018 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import argparse
import json
import logging
import logging.config
import os
import sys

try:
    import yaml
except ImportError:
    yaml = None

import pbr.version

from pbrx import container_images
from pbrx import siblings

log = logging.getLogger("pbrx")


def _read_logging_config_file(filename):
    if not os.path.exists(filename):
        raise ValueError("Unable to read logging config file at %s", filename)

    ext = os.path.splitext(filename)[1]
    if ext in (".yml", ".yaml"):
        if not yaml:
            raise ValueError(
                "PyYAML not installed but a yaml logging config was provided."
                " Install PyYAML, or convert the config to JSON."
            )

            return yaml.safe_load(open(filename, "r"))

    elif ext == ".json":
        return json.load(open(filename, "r"))

    return filename


def setup_logging(log_config, debug):
    if log_config:
        config = _read_logging_config_file(log_config)
        if isinstance(config, dict):
            logging.config.dictConfig(config)
        else:
            logging.config.fileConfig(config)
    else:
        log.addHandler(logging.StreamHandler())
        log.setLevel(logging.DEBUG if debug else logging.INFO)


def main():
    parser = argparse.ArgumentParser(
        description="pbrx: Utilities for projects using pbr"
    )
    parser.add_argument(
        "--version",
        action="version",
        version=str(pbr.version.VersionInfo("pbrx")),
    )
    parser.add_argument(
        "--debug", help="Emit debug output", action="store_true"
    )
    parser.add_argument(
        "--log-config",
        help="Path to a logging config file. Takes precedence over --debug",
    )

    subparsers = parser.add_subparsers(
        title="commands", description="valid commands",
        dest="command", help="additional help"
    )

    cmd_siblings = subparsers.add_parser(
        "install-siblings", help="install sibling packages"
    )
    cmd_siblings.set_defaults(func=siblings.main)
    cmd_siblings.add_argument(
        "-c,--constraints",
        dest="constraints",
        help="Path to constraints file",
        required=False,
    )
    cmd_siblings.add_argument(
        "projects", nargs="*", help="List of project src dirs to process"
    )

    cmd_images = subparsers.add_parser(
        "build-images", help="build per-process container images"
    )
    cmd_images.set_defaults(func=container_images.build)
    cmd_images.add_argument(
        "--prefix",
        help="Organization prefix container images will be published to"
    )
    cmd_images.add_argument(
        "--mirror",
        help=(
            "Base url for an alpine mirror to use. Will be used to replace"
            " http://dl-cdn.alpinelinux.org/alpine"),
    )

    args = parser.parse_args()
    setup_logging(args.log_config, args.debug)

    if not args.command:
        parser.print_help()
        return 1

    try:
        return args.func(args)
    except Exception as e:
        log.exception(str(e))
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
