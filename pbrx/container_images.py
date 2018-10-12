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
try:
    import configparser
except ImportError:
    import ConfigParser as configparser

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
        self.create()
        log.debug(
            "Used base image {base} at sha {sha}".format(
                base=self._base,
                sha=sh.docker.images('-q', self._base).strip(),
            ))

        self._cont = sh.docker.bake("exec", self.run_id, "sh", "-c",
                                    _truncate_exc=False)

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
        self.run_id = sh.docker('start', container_id).strip()
        log.debug("Started container %s", self.run_id)

    def run(self, command):
        log.debug("Running: %s", command)
        output = self._cont(command)
        log.debug(output)
        return output

    def commit(self, image, tag=None, comment=None):
        '''Apply a commit to the current container.

        A new local image based on the current container is created with
        the commit (name format of "image:tag").

        :param str image: The local image name to create. This should
            include any prefix (e.g., username/repository) appropriate for
            pushing to a registry. If the image already exists, it is
            overwritten.
        :param str tag: The tag to apply to the new repo. If not supplied,
            the docker default "latest" is used.
        :param str comment: A commit message to apply to the new repo.
        '''
        commit_args = []
        if comment:
            commit_args.append("-c")
            commit_args.append(comment)
        commit_args.append(self.run_id)
        if image:
            if tag:
                image = ":".join([image, tag])
            commit_args.append(image)
        log.debug("Committing container %s to %s", self.run_id, image)
        sh.docker.commit(*commit_args)


@contextlib.contextmanager
def docker_container(base, image=None, prefix=None, comment=None, volumes=None):
    '''Context manager to use for container runs.

    This will start a new container, optionally commit it to a new local
    image, and remove the container at exit.

    :param str base: Name of base image to use for the container.
    :param str image: Image name to use for the new local image. If not
        supplied, no local image is created.
    :param str prefix: Prefix to apply to the new local image name.
    :param str comment: Commit message to use for the new local image.
    :param list volumes: List of volumes to bind to the container.
    '''
    container = ContainerContext(base, volumes)
    yield container

    if image:
        if prefix:
            image = "/".join([prefix, image])
        container.commit(image, comment=comment)

    log.debug("Removing container %s", container.run_id)
    sh.docker.rm("-f", container.run_id)


def build(args):

    info = ProjectInfo()

    log.info("Building base python container")
    # Create base python container which has distro packages updated
    with docker_container("python:alpine", image="python-base") as cont:
        if args.mirror:
            cont.run("sed -i 's,{old},{new}' /etc/apk/repositories".format(
                old=ALPINE_MIRROR_BASE,
                new=args.mirror))
        cont.run("apk update")

    log.info("Building bindep container")
    # Create bindep container
    with docker_container("python-base", image="bindep") as cont:
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
                # NOTE(Shrews): The non-prefixed container names are referenced
                # in the extras section.
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
                image=info.base_container,
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

                    # We already have a base container built that we'll use
                    # for the other images, but it may be prefixed.
                    base = info.base_container
                    if args.prefix:
                        base = "/".join([args.prefix, base])

                    with docker_container(
                        base,
                        image=script,
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


def push(args):
    '''Push any built images to the registry.

    The images built by pbrx's build-image command should already be named
    with a prefix (the repository name to push to). It is expected that
    we are already logged in to the registry as the user that owns the
    repository.
    '''
    info = ProjectInfo()

    unprefixed_image_names = info.scripts.copy()
    unprefixed_image_names.add(info.base_container)

    for image in unprefixed_image_names:
        image = "/".join([args.prefix, image])
        log.info("Pushing {image}".format(image=image))
        sh.docker.push(image)
