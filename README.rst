====
pbrx
====

Utilities for projects using `pbr`_.

`pbr`_ is very opinionated about how things should be done. As a result,
there are a set of actions that become easy to deal with generically for
any `pbr`_ based project. **pbrx** is a collection of utilities that contain
support for such actions.

.. note::

  Each of the utilities has a primary focus of working for projects using
  pbr. However, some of them will also work just fine for non-pbr-based
  projects. When that is the case, the utility will be marked appropriately.

* Free software: Apache license
* Documentation: https://docs.openstack.org/pbrx/latest
* Source: https://git.openstack.org/cgit/openstack/pbrx

Features
--------

Each utility is implemented as a subcommand on the ``pbrx`` command.

install-siblings
  Updates an installation with local from-source versions of dependencies.
  For any dependency that the normal installation installed from pip/PyPI,
  ``install-siblings`` will look for an adjacent git repository that provides
  the same package. If one exists, the source version will be installed to
  replace the released version. This is done in such a way that any given
  ``constraints`` will be honored and not get messed up by transitive depends.

build-images
  Builds container images from a project's source tree. The ``python:alpine``
  base image is used, and dependencies are taken from ``bindep.txt`` for
  distro requirements and ``requirements.txt`` for python requirements. A
  base image is made for the project itself, and then an additional image
  based on the base image for every entry in ``entry_points.console_scripts``
  in the ``setup.cfg`` file.

.. _pbr: https://docs.openstack.org/pbr/latest/
