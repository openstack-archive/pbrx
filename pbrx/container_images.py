# Copyright 2018 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import configparser
import contextlib
import os
import tempfile

import sh


class ProjectInfo(object):

    def __init__(self):
        self.config = configparser.ConfigParser()
        self.config.read("setup.cfg")
        self.scripts = self._extract_scripts()
        self.name = self.config.get("metadata", "name")

    def _extract_scripts(self):
        console_scripts = self.config.get("entry_points", "console_scripts")
        scripts = set()
        for line in console_scripts.strip().split("\n"):
            parts = line.split("=")
            if len(parts) != 2:
                continue

            scripts.add(parts[0].strip())
        return scripts

    @property
    def base_container(self):
        return "{name}-base".format(name=self.name)


class ContainerContext(object):

    def __init__(self, base, volumes):
        self._base = base
        self._volumes = volumes or []
        self.run_id = self.create()
        self._cont = sh.docker.bake("exec", self.run_id, "bash", "-c")

    def create(self):
        vargs = [
            "create",
            "--rm",
            "-it",
            "-v",
            "{}:/usr/src".format(os.path.abspath(os.curdir)),
            "-w",
            "/usr/src",
            "-v",
            "{}:/root/.cache/pip/wheels".format(
                os.path.expanduser("~/.cache/pip/wheels")),
        ]
        for vol in self._volumes:
            vargs.append("-v")
            vargs.append(vol)
        vargs.append(self._base)
        vargs.append("bash")

        container_id = sh.docker(*vargs).strip()
        return sh.docker('start', container_id).strip()

    def run(self, command):
        self._cont(command)

    def commit(self, tag, comment=None, prefix=None):
        commit_args = []
        if comment:
            commit_args.append("-c")
            commit_args.append(comment)
        commit_args.append(self.run_id)
        commit_args.append(tag)
        sh.docker.commit(*commit_args)
        if prefix:
            sh.docker.tag(
                tag, "{prefix}/{tag}".format(prefix=prefix, tag=tag)
            )


@contextlib.contextmanager
def docker_container(base, tag=None, prefix=None, comment=None, volumes=None):
    container = ContainerContext(base, volumes)
    yield container

    # Make sure wheels made in the container are owned by the current user
    container.run("chown -R {uid} /root/.cache/pip/wheels".format(
        uid=os.getuid()))
    if tag:
        container.commit(tag, prefix=prefix, comment=comment)
    sh.docker.rm("-f", container.run_id)


def build(args):

    info = ProjectInfo()

    # Create base python container which has distro packages updated
    with docker_container("python:slim", tag="python-base") as cont:
        cont.run("apt-get update")

    # Create bindep container
    with docker_container("python-base", tag="bindep") as cont:
        cont.run("apt-get install -y lsb-release")
        cont.run("pip install bindep")

    # Use bindep container to get list of packages needed in the final
    # container. It returns 1 if there are packages that need to be installed.
    try:
        packages = sh.docker.run(
            "--rm",
            "-v",
            "{pwd}:/usr/src".format(pwd=os.path.abspath(os.curdir)),
            "bindep",
            "bindep",
            "-b",
        )
    except sh.ErrorReturnCode_1 as e:
        packages = e.stdout.decode('utf-8').strip()

    try:
        build_packages = sh.docker.run(
            "--rm",
            "-v",
            "{pwd}:/usr/src".format(pwd=os.path.abspath(os.curdir)),
            "bindep",
            "bindep",
            "-b",
            "build",
        )
    except sh.ErrorReturnCode_1 as e:
        build_packages = e.stdout.decode('utf-8').strip()
    packages = packages.replace("\r", "\n").replace("\n", " ")
    build_packages = build_packages.replace("\r", "\n").replace("\n", " ")

    # Make place for the wheels to go
    with tempfile.TemporaryDirectory(
        dir=os.path.abspath(os.curdir)
    ) as tmpdir:
        tmp_volume = "{tmpdir}:/tmp/output".format(tmpdir=tmpdir)

        # Make temporary container that installs all deps to build wheel
        # This container also needs git installed for pbr
        with docker_container("python-base", volumes=[tmp_volume]) as cont:
            cont.run("apt-get install -y {build_packages} git".format(
                build_packages=build_packages))
            cont.run("python setup.py bdist_wheel -d /tmp/output")
            cont.run("chmod -R ugo+w /tmp/output")

        # Build the final base container. Use dumb-init as the entrypoint so
        # that signals and subprocesses work properly.
        with docker_container(
            "python-base",
            tag=info.base_container,
            prefix=args.prefix,
            volumes=[tmp_volume],
            comment='ENTRYPOINT ["/usr/local/bin/dumb-init", "--"]',
        ) as cont:
            try:
                cont.run(
                    "apt-get install -y {packages} {build_packages}".format(
                        build_packages=build_packages, packages=packages)
                )
                cont.run("pip install -r requirements.txt")
                cont.run("pip install --no-deps /tmp/output/*whl dumb-init")
            except Exception as e:
                print(e.stdout)
                raise

    # Build a container for each program.
    # In the simple-case, it's just an entrypoint commit setting CMD.
    # If a Dockerfile exists for the program, use it instead.
    # Such a Dockerfile should use:
    #   FROM {{ base_container }}-base
    # This is useful for things like zuul-executor where the full story is not
    # possible to express otherwise.
    for script in info.scripts:
        dockerfile = "Dockerfile.{script}".format(script=script)
        if os.path.exists(dockerfile):
            sh.docker.build("-f", dockerfile, "-t", script, ".")
        else:
            with docker_container(
                info.base_container,
                prefix=args.prefix,
                comment='CMD ["/usr/local/bin/{script}"]'.format(
                    script=script
                ),
            ):
                pass
