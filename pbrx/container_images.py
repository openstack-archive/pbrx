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
import logging
import os
import tempfile

import sh

ALPINE_MIRROR_BASE = "http://dl-cdn.alpinelinux.org/alpine"
log = logging.getLogger("pbrx.container_images")


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
        # bind-mount the pip.conf from the host so that any configured
        # pypi mirrors will be used inside of the image builds.
        if os.path.exists('/etc/pip.conf'):
            self._volumes.append('/etc/pip.conf:/etc/pip.conf')
        if os.path.exists(os.path.expanduser('~/.config/pip/pip.conf')):
            self._volumes.append('{host}:{guest}'.format(
                host=os.path.expanduser('~/.config/pip/pip.conf'),
                guest='/root/.config/pip/pip.conf'))
        self.run_id = self.create()
        self._cont = sh.docker.bake("exec", self.run_id, "sh", "-c")

    def create(self):
        vargs = [
            "create",
            "--rm",
            "-it",
            "-v",
            "{}:/usr/src".format(os.path.abspath(os.curdir)),
            "-w",
            "/usr/src",
        ]
        for vol in self._volumes:
            vargs.append("-v")
            vargs.append(vol)
        vargs.append(self._base)
        vargs.append("sh")

        container_id = sh.docker(*vargs).strip()
        return sh.docker('start', container_id).strip()

    def run(self, command):
        log.debug("Running: %s", command)
        output = self._cont(command)
        log.debug(output)
        return output

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

    if tag:
        container.commit(tag, prefix=prefix, comment=comment)
    sh.docker.rm("-f", container.run_id)


def build(args):

    info = ProjectInfo()

    log.info("Building base python container")
    # Create base python container which has distro packages updated
    with docker_container("python:alpine", tag="python-base") as cont:
        if args.mirror:
            cont.run("sed -i 's,{old},{new}' /etc/apk/repositories".format(
                old=ALPINE_MIRROR_BASE,
                new=args.mirror))
        cont.run("apk update")

    log.info("Building bindep container")
    # Create bindep container
    with docker_container("python-base", tag="bindep") as cont:
        cont.run("pip install bindep")

    # Use bindep container to get list of packages needed in the final
    # container. It returns 1 if there are packages that need to be installed.
    log.info("Get list of bindep packages for run")
    try:
        packages = sh.docker.run(
            "--rm",
            "-v",
            "{pwd}:/usr/src".format(pwd=os.path.abspath(os.curdir)),
            "bindep",
            "bindep",
            "-b",
        )
        log.debug(packages)
    except sh.ErrorReturnCode_1 as e:
        packages = e.stdout.decode('utf-8').strip()

    try:
        log.info("Get list of bindep packages for compile")
        compile_packages = sh.docker.run(
            "--rm",
            "-v",
            "{pwd}:/usr/src".format(pwd=os.path.abspath(os.curdir)),
            "bindep",
            "bindep",
            "-b",
            "compile",
        )
        log.debug(compile_packages)
    except sh.ErrorReturnCode_1 as e:
        compile_packages = e.stdout.decode('utf-8').strip()
    packages = packages.replace("\r", "\n").replace("\n", " ")
    compile_packages = compile_packages.replace("\r", "\n").replace("\n", " ")

    # Make place for the wheels to go
    with tempfile.TemporaryDirectory(
        dir=os.path.abspath(os.curdir)
    ) as tmpdir:
        try:
            # Pass in the directory into ~/.cache/pip so that the built wheel
            # cache will persist into the next container. The real wheel cache
            # will go there but we'll also put our built wheel there.
            tmp_volume = "{tmpdir}:/root/.cache/pip".format(tmpdir=tmpdir)

            # Make temporary container that installs all deps to build wheel
            # This container also needs git installed for pbr
            log.info("Build wheels in python-base container")
            with docker_container("python-base", volumes=[tmp_volume]) as cont:
                # Make sure wheel cache dir is owned by container user
                cont.run("chown -R $(whoami) /root/.cache/pip")

                # Add the compile dependencies
                cont.run("apk add {compile_packages} git".format(
                    compile_packages=compile_packages))

                # Build a wheel so that we have an install target.
                # pip install . in the container context with the mounted
                # source dir gets ... exciting.
                cont.run("python setup.py bdist_wheel -d /root/.cache/pip")

                # Install with all container-related extras so that we populate
                # the wheel cache as needed.
                cont.run(
                    "pip install"
                    " $(echo /root/.cache/pip/*.whl)[{base},{scripts}]".format(
                        base=info.base_container.replace('-', '_'),
                        scripts=','.join(info.scripts).replace('-', '_')))

            # Build the final base container. Use dumb-init as the entrypoint
            # so that signals and subprocesses work properly.
            log.info("Build base container")
            with docker_container(
                "python-base",
                tag=info.base_container,
                prefix=args.prefix,
                volumes=[tmp_volume],
                comment='ENTRYPOINT ["/usr/bin/dumb-init", "--"]',
            ) as cont:
                try:
                    cont.run(
                        "apk add {packages} dumb-init".format(
                            packages=packages)
                    )
                    cont.run(
                        "pip install"
                        " $(echo /root/.cache/pip/*.whl)[{base}]".format(
                            base=info.base_container.replace('-', '_')))
                    if args.mirror:
                        cont.run(
                            "sed -i 's,{old},{new}'"
                            " /etc/apk/repositories".format(
                                old=args.mirror,
                                new=ALPINE_MIRROR_BASE))
                    # chown wheel cache back so the temp dir can delete it
                    cont.run("chown -R {uid} /root/.cache/pip".format(
                        uid=os.getuid()))
                except Exception as e:
                    print(e.stdout)
                    raise

            # Build a container for each program.
            # In the simple-case, it's just an entrypoint commit setting CMD.
            # If a Dockerfile exists for the program, use it instead.
            # Such a Dockerfile should use:
            #   FROM {{ base_container }}-base
            # This is useful for things like zuul-executor where the full
            # story is not possible to express otherwise.
            for script in info.scripts:
                dockerfile = "Dockerfile.{script}".format(script=script)
                if os.path.exists(dockerfile):
                    log.info(
                        "Building container for {script} from"
                        " Dockerfile".format(script=script))
                    sh.docker.build("-f", dockerfile, "-t", script, ".")
                else:
                    log.info(
                        "Building container for {script}".format(
                            script=script))
                    with docker_container(
                        info.base_container,
                        tag=script,
                        prefix=args.prefix,
                        volumes=[tmp_volume],
                        comment='CMD ["/usr/local/bin/{script}"]'.format(
                            script=script
                        ),
                    ) as cont:
                        cont.run(
                            "pip install"
                            " $(echo /root/.cache/pip/*.whl)[{script}]".format(
                                script=script.replace('-', '_')))

        finally:
            # chown wheel cache back so the temp dir can delete it
            with docker_container(
                "python-base",
                volumes=[tmp_volume],
            ) as cont:
                cont.run(
                    "chown -R {uid} /root/.cache/pip".format(uid=os.getuid()))
