================================
Installation of Sibling Packages
================================

There are times, both in automated testing, and in local development, where
one wants to install versions of a project from git that are referenced in
a requirements file, or that have somehow already been installed into a given
environment.

This can become quite complicated if a constraints file is involved, as the
git versions don't match the versions in the constraints file. But if a
constraints file is in play, it should also be used for the installation of
the git versions of the additional projects so that their transitive depends
may be properly constrained.

To help with this, `pbrx` provides the ``install-siblings`` command. It takes
a list of paths to git repos to attempt to install, as well as an optional
constraints file.

It will only install a git repositoriy if there is already a corresponding
version of the package installed. This way it is safe to have other repos
wind up in the package list, such as if a Zuul job had a Depends-On including
one or more additional packages that were being put in place for other
purposes.

``pbrx siblings`` expects to be run in root source dir of the primary project.
Sibling projects may be given as relative or absolute paths.

For example, assume the following directory structure:

.. code-block:: none

   $ tree -ld -L 3
   ├── git.openstack.org
   │   ├── openstack
   │   │   ├── keystoneauth
   │   │   ├── python-openstackclient
   │   │   ├── python-openstacksdk
   │   │   ├── requirements

The user is in the ``git.openstack.org/openstack/python-openstackclient`` and
has installed the code into a virtualenv called ``venv``.
``python-openstackclient`` has the following requirements:

.. code-block:: none

  keystoneauth1>=3.3.0 # Apache-2.0
  openstacksdk>=0.9.19 # Apache-2.0

And in the ``git.openstack.org/openstack/requirements`` directory is a file
called ``upper-constraints.txt`` which contains:

.. code-block:: none

  keystoneauth1===3.4.0
  openstacksdk===0.11.3
  requests===2.18.4

The command:

.. code-block:: none

  $ venv/bin/pbrx install-siblings ../keystoneauth

would result in an installation of the contents of ``../keystoneauth``, since
``keystoneauth1`` is already installed and the package name in the
``git.openstack.org/openstack/keystoneauth`` directory is ``keystoneauth1``.
No constraints are given, so any transitive dependencies that are
in ``git.openstack.org/openstack/keystoneauth`` will be potentially installed
unconstrained.

.. code-block:: none

  $ venv/bin/pbrx install-siblings -c ../requirements/upper-constraints.txt ../keystoneauth

Will also update ``keystoneauth1``, but will apply constraints properly to
any transitive depends.

.. code-block:: none

  $ venv/bin/pbrx install-siblings -c ../requirements/upper-constraints.txt ../keystoneauth ../python-openstacksdk

will install both ``keystoneauth1`` and ``openstacksdk``.

.. code-block:: none

  $ venv/bin/pbrx install-siblings -c ../requirements/upper-constraints.txt ../keystoneauth ../python-openstacksdk ../requirements

will also install both ``keystoneauth1`` and ``openstacksdk``. Even though
``git.openstack.org/openstack/requirements`` is itself a python package, since
it is not one of the ``python-openstackclient`` dependencies, it will be
skipped.
