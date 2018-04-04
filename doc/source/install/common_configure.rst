2. Edit the ``/etc/pbrx/pbrx.conf`` file and complete the following
   actions:

   * In the ``[database]`` section, configure database access:

     .. code-block:: ini

        [database]
        ...
        connection = mysql+pymysql://pbrx:PBRX_DBPASS@controller/pbrx
