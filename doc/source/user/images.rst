=========================
Building Container Images
=========================

Python projects that declare their distro dependencies using `bindep`_
can be built into container images without any additional duplicate
configuration. The `pbrx` command ``build-images`` does this as minimally
and efficiently as possible. The aim is to produce single-process application
images that container only those things needed at runtime.

When ``pbrx build-images`` is run in a project source directory, the result
will be a base image, named '{project}-base', and then an image for each
entry in ``entry_points.console_scripts`` with ``CMD`` set to that console
script. For instance, in a python project "foo" that provides console scripts
called "foo-manage" and "foo-scheduler", ``pbrx build-images`` will result in
container images called "foo-base", "foo-manage" and "foo-scheduler".

``pbrx build-images`` uses volume mounts during the image build process instead
of copying to prevent wasted energy in getting source code into the image and
in getting artifacts out of the image. This makes it well suited for use on
laptops or in automation that has access to something that behaves like a full
computer but at the moment less well suited for use in unprivileged container
systems. Work will be undertaken to remove this limitation.

Distro Depends
==============

``build-images`` relies on `bindep`_ and ``bindep.txt`` to get the list of
packages to install.

``build-images`` uses the Builder Image pattern so that one image is used to
make wheels of the project and its dependencies, and another to install the
package. Distro packages needed to build wheels of a project or its python
depends from source should be marked with a ``compile`` profile in
``bindep.txt``. Distro packages needed at runtime should not be marked with
a profile.

``build-images`` uses ``python:alpine`` as a base image. There are no plans
or intent to make that configurable since these are application images and
the guest distro only serves to provide Python and c-library depends. To mark
dependencies in ``bindep.txt`` for images, the ``platform:apline`` profile
can be used.

The following is an example bindep file:

::

  gcc [compile test platform:rpm platform:apk]
  libffi-devel [compile test platform:rpm]
  libffi-dev [compile test platform:dpkg platform:apk]
  libffi [platform:apk]
  libressl-dev [compile test platform:apk]
  linux-headers [compile test platform:apk]
  make [compile test platform:apk]
  musl-dev [compile test platform:apk]

The only library needed at runtime is ``libffi``. The other dependencies are
all marked ``compile`` so will be installed into the build container but
not the final runtime container. `bindep`_ is useful not just for building
containers, so entries for ``libffi-dev`` on debian as well as ``libffi-devel``
on Red Hat are there. Also, this example marks some packages as needed for
``test``. `pbrx` and `bindep`_ appropriately ignore this information.

.. note::
  Because of the use of the ``python:alpine`` image, it is not necessary to
  list ``python3-dev`` in ``platform:alpine``.

Python Dependencies
===================

``build-images`` uses normal python mechanisms to get python dependencies.
Namely, it runs ``pip install .`` in the mounted source directory.

In most cases this is sufficient, but there are times when a single set of
dependencies for a set of console-scripts might not be appropriate. In this
case, it is possible to add a Python extra entry for a console script to add
additional python dependencies. For instance, this section in ``setup.cfg``:

::

  [extras]
  zuul_base =
      PyMySQL
      psycopg2-binary
  zuul_executor =
      ara

Will cause ``PyMySQL`` and ``psycopg2-binary`` to be installed into the base
image (even though they are optional dependencies for a normal install) and
for ``ara`` to be installed in the ``zuul-executor`` image.

.. note::

  It is important to note that underscores must be used in the extras
  definition in place of dashes.

.. _bindep: https://docs.openstack.org/infra/bindep/
