Prerequisites
-------------

Before you install and configure the pbrx service,
you must create a database, service credentials, and API endpoints.

#. To create the database, complete these steps:

   * Use the database access client to connect to the database
     server as the ``root`` user:

     .. code-block:: console

        $ mysql -u root -p

   * Create the ``pbrx`` database:

     .. code-block:: none

        CREATE DATABASE pbrx;

   * Grant proper access to the ``pbrx`` database:

     .. code-block:: none

        GRANT ALL PRIVILEGES ON pbrx.* TO 'pbrx'@'localhost' \
          IDENTIFIED BY 'PBRX_DBPASS';
        GRANT ALL PRIVILEGES ON pbrx.* TO 'pbrx'@'%' \
          IDENTIFIED BY 'PBRX_DBPASS';

     Replace ``PBRX_DBPASS`` with a suitable password.

   * Exit the database access client.

     .. code-block:: none

        exit;

#. Source the ``admin`` credentials to gain access to
   admin-only CLI commands:

   .. code-block:: console

      $ . admin-openrc

#. To create the service credentials, complete these steps:

   * Create the ``pbrx`` user:

     .. code-block:: console

        $ openstack user create --domain default --password-prompt pbrx

   * Add the ``admin`` role to the ``pbrx`` user:

     .. code-block:: console

        $ openstack role add --project service --user pbrx admin

   * Create the pbrx service entities:

     .. code-block:: console

        $ openstack service create --name pbrx --description "pbrx" pbrx

#. Create the pbrx service API endpoints:

   .. code-block:: console

      $ openstack endpoint create --region RegionOne \
        pbrx public http://controller:XXXX/vY/%\(tenant_id\)s
      $ openstack endpoint create --region RegionOne \
        pbrx internal http://controller:XXXX/vY/%\(tenant_id\)s
      $ openstack endpoint create --region RegionOne \
        pbrx admin http://controller:XXXX/vY/%\(tenant_id\)s
