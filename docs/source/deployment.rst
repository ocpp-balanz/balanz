Deployment
==========

The suggested deployment structure is to start :term:`balanz` at the root of:

.. code-block:: 
    :caption: Suggested deployment directory/file structure

    ./config
    ./config/balanz.ini
    ./history
    ./history/sessions.csv
    ./model
    ./model/chargers.csv
    ./model/groups.csv
    ./model/tags.csv
    ./cert/
    ./cert/cert-chain.pem
    ./cert/cert.key


Such a structure can easily be created by copying and adjusting the ``data`` directory from the :term:`balanz` sources,
adding the necessary certificate files if running :term:`balanz` over ``wss``.


Building and Starting balanz
-----------------------------

Before running :term:`balanz` the necesarry prerequisites must be installed. This can be achieved with::

    make intall

:term:`balanz` may be started simply be running the following command in the ``balanz`` directory::

    python balanz.py --config <path_to_config_file>   

or, alternatively, by issuing::

    make run


docker
------

Even if it is possible to start :term:`balanz` directly as mentioned above it is recommended
to build and run :term:`balanz` as a docker container. This ensures full consistency in terms of python versions, etc.
A ``Dockerfile`` is available for building the image. To build the container image, either run::

    make docker

or::

    docker build -t balanz .

Included in the ``examples/docker`` directory is a ``docker-compose`` example, repeated below for completeness. Adjust it as 
required.

.. literalinclude :: ../../examples/docker/compose.yaml
   :language: text
   :caption: Example Docker Compose file


docker hub/docker.io
--------------------

Prebuilt and versioned images will be available on `docker-hub <https://hub.docker.com/r/jensdock/balanz>`_.

Pull the latest image by doing::

    docker pull jensdock/balanz

