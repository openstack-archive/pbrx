# Copyright (c) 2018 Red Hat
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

try:
    import configparser
except ImportError:
    import ConfigParser as configparser

import logging
import os
import pkg_resources
import subprocess
import sys
import tempfile

log = logging.getLogger("pbrx")


def get_package_name(setup_cfg):
    """Get package name from a setup.cfg file."""
    try:
        c = configparser.ConfigParser()
        c.read(setup_cfg)
        return c.get("metadata", "name")

    except Exception:
        log.debug("No name in %s", setup_cfg)
        return None


def get_requires_file(dist):
    """Get the path to the egg-info requires.txt file for a given dist."""
    return os.path.join(
        os.path.join(dist.location, dist.project_name + ".egg-info"),
        "requires.txt",
    )


def get_installed_packages():
    """Get the correct names of the currently installed packages."""
    return [f.project_name for f in pkg_resources.working_set]


def pip_command(*args):
    """Execute a pip command in the current python."""
    pip_args = [sys.executable, "-m", "pip"] + list(args)
    log.debug("Executing %s", " ".join(pip_args))
    output = subprocess.check_output(pip_args, stderr=subprocess.STDOUT)
    for line in output.decode("utf-8").split("\n"):
        log.debug(line)
    return output


class Siblings(object):

    def __init__(self, name, projects, constraints):
        self.name = name
        self.projects = projects
        self.constraints = constraints
        self.packages = {}
        self.get_siblings()
        log.info(
            "Sibling Processing for %s from %s",
            self.name,
            os.path.abspath(os.path.curdir),
        )

    def get_siblings(self):
        """Finds all python packages that are there.

        From the list of provided source dirs, find all of the ones that are
        python projects and return a mapping of their package name to their
        src_dir.

        We ignore source dirs that are not python packages so that this can
        be used with the list of all dependencies from a Zuul job. In the
        future we might want to add a flag that causes that to be an error
        for local execution.
        """
        self.packages = {}

        for root in self.projects:
            root = os.path.abspath(root)
            name = None
            setup_cfg = os.path.join(root, "setup.cfg")
            found_python = False
            if os.path.exists(setup_cfg):
                found_python = True
                name = get_package_name(setup_cfg)
                self.packages[name] = root
            if not name and os.path.exists(os.path.join(root, "setup.py")):
                found_python = True
                # It's a python package but doesn't use pbr, so we need to run
                # python setup.py --name to get setup.py to tell us what the
                # package name is.
                name = subprocess.check_output(
                    [sys.executable, "setup.py", "--name"],
                    cwd=root,
                    stderr=subprocess.STDOUT,
                )
                if name:
                    name = name.strip()
                    self.packages[name] = root
            if found_python and not name:
                log.info("Could not find package name for %s", root)
            else:
                log.info("Sibling %s at %s", name, root)

    def write_new_constraints_file(self):
        """Write a temporary constraints file excluding siblings.

        The git versions of the siblings are not going to match the values
        in the constraints file, so write a copy of the constraints file
        that doesn't have them in it, then use that when installing them.
        """
        constraints_file = tempfile.NamedTemporaryFile(delete=False)
        existing_constraints = open(self.constraints, "r")
        for line in existing_constraints.read().split("\n"):
            package_name = line.split("===")[0]
            if package_name in self.packages:
                continue

            constraints_file.write(line.encode("utf-8"))
            constraints_file.write(b"\n")
        constraints_file.close()
        return constraints_file

    def find_sibling_packages(self):
        for package_name in get_installed_packages():
            log.debug("Found %s python package installed", package_name)
            if package_name == self.name:
                # We don't need to re-process ourself. We've filtered
                # ourselves from the source dir list, but let's be sure
                # nothing is weird.
                log.debug("Skipping %s because it's us", package_name)
                continue

            if package_name in self.packages:
                log.debug(
                    "Package %s on system in %s",
                    package_name,
                    self.packages[package_name],
                )

                log.info("Uninstalling %s", package_name)
                pip_command("uninstall", "-y", package_name)
                yield package_name

    def clean_depends(self, installed_siblings):
        """Overwrite the egg-info requires.txt file for siblings.

        When we install siblings for a package, we're explicitly saying
        we want a local git repository. In some cases, the listed requirement
        from the driving project clashes with what the new project reports
        itself to be. We know we want the new project, so remove the version
        specification from the requires.txt file in the main project's
        egg-info dir.
        """
        dist = None
        for found_dist in pkg_resources.working_set:
            if found_dist.project_name == self.name:
                dist = found_dist
                break

        if not dist:
            log.debug(
                "main project is not installed, skipping requires clean"
            )
            return

        requires_file = get_requires_file(dist)
        if not os.path.exists(requires_file):
            log.debug("%s file for main project not found", requires_file)
            return

        new_requires_file = tempfile.NamedTemporaryFile(delete=False)
        with open(requires_file, "r") as main_requires:
            for line in main_requires.readlines():
                found = False
                for name in installed_siblings:
                    if line.startswith(name):
                        log.debug(
                            "Replacing %s with %s in requires.txt",
                            line.strip(),
                            name,
                        )
                        new_requires_file.write(name.encode("utf-8"))
                        new_requires_file.write(b"\n")
                        found = True
                        break

                if not found:
                    new_requires_file.write(line.encode("utf-8"))
        os.rename(new_requires_file.name, requires_file)

    def process(self):
        """Find and install the given sibling projects."""
        installed_siblings = []
        package_args = []
        for sibling_package in self.find_sibling_packages():
            log.info(
                "Installing %s from %s",
                sibling_package,
                self.packages[sibling_package],
            )
            package_args.append("-e")
            package_args.append(self.packages[sibling_package])
            installed_siblings.append(sibling_package)
        if not package_args:
            log.info("Found no sibling packages, nothing to do.")
            return

        args = ["install"]

        if self.constraints:
            constraints_file = self.write_new_constraints_file()
            args.extend(["-c", constraints_file.name])
        args.extend(package_args)

        try:
            pip_command(*args)
        finally:
            os.unlink(constraints_file.name)

        self.clean_depends(installed_siblings)


def main(args):
    if not os.path.exists("setup.cfg"):
        log.info("No setup.cfg found, no action needed")
        return 0

    if not args.projects:
        log.info("No sibling projects given, no action needed.")
        return 0

    if args.constraints and not os.path.exists(args.constraints):
        log.info("Constraints file %s was not found", args.constraints)
        return 1

    # Who are we?
    package_name = get_package_name("setup.cfg")
    if not package_name:
        log.info("No name in main setup.cfg, skipping siblings")
        return 0

    siblings = Siblings(package_name, args.projects, args.constraints)
    siblings.process()
    return 0
