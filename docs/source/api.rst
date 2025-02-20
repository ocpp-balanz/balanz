API
===

:term:`balanz` includes an API primary focused on supporting external clients (UI, automation, etc.)

The API is a WebSocket based protocol parallel to the :term:`OCPP` protocol used with Charger/Servers.

The protocol is designed to be simple and easy to use, mimicing :term:`OCPP` messages. To recap, commands are sent
as JSON messages in the format ``[2, <messageId>, <command>, <payload>]``. Succesful responses sent as 
``[3, <messageId>, <payload>]`` while error responses are ``[4, <messageId>, <errorMessage>]``.

The client is expected to Authenticate using the `Login` call before issuing other commands. Otherwise,
they will be rejected. The sha256 value of token specified in a list in the balanz configuration file.
An online tool may be used, e.g. `Coding Tools <https://coding.tools/sha256>`_. Set the tool to generate
lower case sha256 values as in the example below (first sha matches the token set in the example UIs).

.. code-block:: text
    :caption: Example of API token sha setting

    [api]
    ; Comma-separated list of valid sha256 values for login tokens. 
    token_shas = 4a8b74ba66bb2dad068addac37fa6faaa8996ca84a4d94bdc12a54e4e2732a6a,4a8b74ba66bb2dad068addac37fa6faaa8996ca84a4d94bdc12a54e4e2732a64


Model commands
--------------

The protocol supports the following commands for interacting with the :term:`balanz` model. The resulting payloads
are not detailed, but should be quite intiutive. Try the commands - maybe using the included example UI -
(see TBD). 

.. list-table:: balanz model commands
   :widths: 25 30 45
   :header-rows: 1

   * - Command
     - Payload
     - Description
   * - ``Login``
     - ``token``
     - Authenticate
   * - ``GetStatus``
     - (None)
     - Returns balanz version and various status information.
   * - ``DrawAll``
     - (None)
     - Returns drawing of all groups, chargers, sessions, and states.
   * - ``SetChargePriority``
     - ``charger_id, alias, connector_id, priority``
     - Update the priority of a session on a connector. 
   * - ``SetBalanzState``
     - ``group_id, suspend`` (True or False)
     - Suspend or resume balanz() for an allocation group
   * - ``GetGroups``
     - (None)
     - Returns full group structure.
   * - ``GetChargers``
     - ``group_id, charger_id``
     - Returns charger(s) matching filter
   * - ``ReloadChargers``
     - (None)
     - Rereads chargers from CSV file
   * - ``WriteChargers``
     - (None)
     - Write chargers from CSV file
   * - ``UpdateCharger``
     - ``charger_id, alias, priority, description, conn_max``
     - Update existing charger. Updates specified field(s). 
   * - ``GetTags``
     - (None)
     - Returns all known tags
   * - ``ReloadTags``
     - (None)
     - Reread tags from CSV file
   * - ``WriteTags``
     - (None)
     - Write tags to CSV file
   * - ``UpdateTag``
     - ``id_tag, user_name, description, status, priority``
     - Update existing tag. Updates specified field(s). status can be ``activated`` or ``blocked``
   * - ``GetSessions``
     - ``charger_id, group_id``
     - Returns all historic sessions matching filter
   * - ``SetLogLevel``
     - ``component, loglevel``
     - Dynamically update log level. See list of components in the balanz configuration file. 
       loglevel may be ``ERROR``, ``WARNING``, ``INFO``, or ``DEBUG``

For example, to return all chargers belonging to the ``RR2`` group, send the following command
setting ``messageId`` to ``123456``::

    [2, "123456", "GetChargers", {"group_id": "RR2"}]



OCPP Commands
-------------

The following commands closely related to :term:`OCPP` calls are also supported on the API,
mostly for debugging and troubleshooting purposes. 

WARNING: These commands may be taken out of the API; possibly to be replaced with a single call to allow
pass-through of any valid :term:`OCPP` command.

Most commands (all commands taking charger_id as argument) will result in a single
:term:`OCPP` call towards the charger without involving other balanz logic. As such, care
must be taken not to interfeere with balanz.

There is little error checking vs. screening format of the payloads for the commands.
Errors may be found only when issued to the charger. Such errors will of course be
reported.

.. list-table:: OCPP commands
   :widths: 25 30 45
   :header-rows: 1

   * - Command
     - Payload
     - Description
   * - ``ClearDefaultProfiles``
     - ``charger_id``
     - Clears all default charing profiles
   * - ``ClearDefaultProfile``
     - ``charger_id, charging_profile_id``
     - Clears a specific default charging profile
   * - ``SetTxProfile``
     - ``charger_id, connector_id, stack_level, limit, transaction_id``
     - Sets profile for transaction
   * - ``Reset``
     - ``charger_id, type`` (Soft or Hard)
     - Resets the charge point
   * - ``RemoteStartTransaction``
     - ``charger_id, connector_id, id_tag``
     - Starts a transaction remotely
   * - ``RemoteStopTransaction``
     - ``charger_id, transaction_id``
     - Stops a transaction remotely
   * - ``GetConfiguration``
     - ``charger_id, [key]`` (list, can be empty or omitted)
     - Get charger configuration for key or all
   * - ``ChangeConfiguration``
     - ``charger_id, key, value``
     - Change charger config for key
   * - ``TriggerMessage``
     - ``charger_id, message_type`` (one of ``MeterValues``, ``BootNotificaton``, ``DiagnosticsStatusNotification``,
       ``FirmwareStatusNotification``, ``Heartbeat``, ``StatusNotification``)
     - Trigger an OCPP message to be sent by the charger

.. note::
  In all calls (model or OCPP calls) where a charger is identified using ``charger_id``, it is 
  possible to instead identify the charger by an alternative ``alias`` argument matching the
  charger alias. If both are supplied, `charger_id` is used.