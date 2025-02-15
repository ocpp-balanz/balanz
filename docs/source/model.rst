Model
=====

The :term:`balanz` model provides the required data structures for driving Smart Charging decisions as well as elements to support
CSMS/CS functionality.

The main components of the model are Groups, Chargers, Sessions, and Tags. The current implementation has, for simplicity,
a CSV-file associated with each of these compnent types. Later versions will support a database backend.


.. _model-group:

Groups
------

A group represents a collection of chargers. For each group, the following attributes are defined:

- ``group_id``: A unique identifier for the group.
- ``description``: A textual description of the group.
- ``max_allocation``: The maximum allocation for the group. If defined, sets the limit for the total allocation of all chargers contained in any child group (or directly in the group).

A group with the ``max_allocation`` attribute set is termed an *allocation group*. 

Groups are defined in a CSV file named ``groups.csv``; file name is configurable.

.. code-block:: text
    :caption: Example `groups.csv` file

    group_id,description,max_allocation
    HQ,HQ Site,00:00-07:59>0=63;08:00-16:59>0=20:3=63;17:00-20:59>5=63;21:00-23:59>0=40:3=63
    RR1,Road Runner 1 Site chargers,00:00-05:59>0=48;06:00-16:59>0=16:3=32:5=48;17:00-20:59>0=0:5=48;21:00-23:59>0=32:5=48
    RR2,Road Runner 2 Site,00:00-23:59>0=24:3=40:5=48
    Default,Default Group for autoregistered chargers,


Note that ``max_allocation`` values (in Amps) are defined as values per priority within a schedule. All 24 hours should be covered
as is the case in the examples above. In this allocation maximum may e.g. be increased during the night where office site 
activities are not as demanding in terms of electricity. A schedule may also specify times in teh day where charging should be
limited, e.g. due to higher electricity costs.

For example, on the ``RR1`` site above in the time interval between 17:00 and 20:59 (most expensive timeslot in Denmark due to
electricity tarrifs), charging with a priority below 5 is completely disabled. If 5 or above, charging can occur with a total
of the full maximum 48 A available.


.. _model-charger:

Chargers
--------

A Charger is naturally the most interesting point of control for :term:`balanz`. It is defined using the following attributes:

- ``charger_id``: A unique identifier for the charger. This is typically hardcoded into the charger.
- ``alias``: A human-readable name for the charger.
- ``group_id``: The ID of the group to which this charger belongs.
- ``no_connectors``: The number of connectors on the charger, typically 1.
- ``priority``: Priority (higher is better) associated with charger connectors.
- ``description``: A description of the charger.
- ``conn_max``: The maximum current that can be drawn from this charger in Amps.
- ``auth_sha``: An authentication SHA-256 hash to verify the charger's identity. This is set by :term:`balanz`.

.. code-block:: text
    :caption: Example part of a `chargers.csv` file

    charger_id,alias,group_id,no_connectors,priority,description,conn_max,auth_sha
    TACW222421G063,HQ-01,HQ,1,1,HQ low priority HQ-01 (limit 8A),8.0,
    TACW212432G692,HQ-02,HQ,1,1,HQ low priority HQ-02 (limit 8A),8.0,
    TACW242432G552,HQ-03,HQ,1,1,HQ low priority HQ-03,32.0,
    TACW227426G469,HQ-11,HQ,1,3,HQ medium priority HQ-11,32.0,
    TACW224437G681,HQ-16,HQ,1,5,HQ high priority HQ-16,32.0,
    TACW224377G584,RR1-01,RR1,1,1,RR1 charger RR1-01,32.0,
    TACW224357G670,RR1-02,RR1,1,1,RR1 charger RR1-02,32.0,
    TACW224327G682,RR1-03,RR1,1,1,RR1 charger RR1-03 (limit 8A),8.0,
    TACW224317G584,RR2-01,RR2,1,3,RR2 high priority RR2-01,32.0,
    TACW224137G670,RR2-02,RR2,1,1,RR2 low priority RR2-02,32.0,
    ...


.. _model_session:

Sessions
--------

A Session represents a completed charging transaction. If configured, :term:`balanz` will log session details to a CSV file for
off-line analysis or processing. Note, that the ``energy`` values is given in kWh.

The ``history`` field is a ``;``-separated list of timestamps and their associated offer values in Amps (A).


.. code-block:: text
    :caption: Example part of a `sessions.csv` file

    session_id,charger_id,id_tag,stop_id_tag,start_time,end_time,duration,energy,stop_reason,history
    TACW242432G552-2025-01-10-05:22:30,TACW242432G552,CA2E214E,CA2E214E,2025-01-10 05:22:30,2025-01-10 05:56:34,00:34:03,9.240,EVDisconnected
    TACW242432G552-2025-01-10-09:33:18,TACW242432G552,CA2E214E,CA2E214E,2025-01-10 09:33:18,2025-01-10 10:38:15,01:04:56,15.326,Local
    TACW242432G552-2025-01-10-14:02:59,TACW242432G552,CA2E214E,CA2E214E,2025-01-10 14:02:59,2025-01-10 21:08:12,07:05:12,17.796,EVDisconnected
    TACW242432G552-2025-01-11-20:31:28,TACW242432G552,624F2732,624F2732,2025-01-11 20:31:28,2025-01-12 08:47:16,12:15:48,33.303,EVDisconnected
    TACW242432G552-2025-01-12-14:22:48,TACW242432G552,624F2732,624F2732,2025-01-12 14:22:48,2025-01-12 14:28:55,00:06:07,0.025,EVDisconnected
    TACW242432G552-2025-01-12-16:37:54,TACW242432G552,624F2732,624F2732,2025-01-12 16:37:54,2025-01-12 16:40:06,00:02:12,0.304,EVDisconnected
    TACW242432G552-2025-01-13-18:17:53,TACW242432G552,624F2732,624F2732,2025-01-13 18:17:53,2025-01-13 18:54:53,00:36:59,30.459,EVDisconnected,2025-01-13 18:54:53=0A
    TACW242432G552-2025-01-15-00:00:17,TACW242432G552,624F2732,624F2732,2025-01-15 00:00:17,2025-01-15 07:33:41,07:33:23,5.115,EVDisconnected,2025-01-15 07:33:41=0A
    TACW242432G552-2025-01-17-09:08:10,TACW242432G552,624F2732,624F2732,2025-01-17 09:08:10,2025-01-17 10:00:09,00:51:59,2.251,EVDisconnected,2025-01-17 10:00:09=0A
    TACW242432G552-2025-01-17-14:17:27,TACW242432G552,624F2732,624F2732,2025-01-17 14:17:27,2025-01-17 18:09:49,03:52:22,11.211,EVDisconnected,2025-01-17 18:09:49=0A
    TACW242432G552-2025-01-17-20:23:37,TACW242432G552,624F2732,624F2732,2025-01-17 20:23:37,2025-01-18 07:58:12,11:34:35,32.733,EVDisconnected,2025-01-18 07:58:12=0A
    TACW242432G552-2025-01-19-15:10:45,TACW242432G552,624F2732,624F2732,2025-01-19 15:10:45,2025-01-19 20:45:43,05:34:58,5.744,EVDisconnected,2025-01-19 20:45:43=0A
    TACW242432G552-2025-01-20-15:16:33,TACW242432G552,ACF33F19,ACF33F19,2025-01-20 15:16:33,2025-01-20 15:42:27,00:25:54,2.587,Remote,2025-01-20 15:16:34=0A;2025-01-20 15:42:27=0A
    TACW242432G552-2025-01-20-22:49:52,TACW242432G552,624F2732,624F2732,2025-01-20 22:49:52,2025-01-21 07:15:53,08:26:01,11.111,EVDisconnected,2025-01-20 22:49:52=0A;2025-01-21 07:15:53=0A
    TACW242432G552-2025-01-21-22:05:57,TACW242432G552,624F2732,624F2732,2025-01-21 22:05:57,2025-01-22 07:25:36,09:19:39,8.731,EVDisconnected,2025-01-21 22:05:56=0A;2025-01-22 07:25:36=0A
    TACW242432G552-2025-01-22-20:46:33,TACW242432G552,624F2732,624F2732,2025-01-22 20:46:33,2025-01-23 05:24:06,08:37:33,9.579,EVDisconnected,2025-01-22 20:46:33=0A;2025-01-23 05:24:06=0A
    TACW242432G552-2025-01-23-15:29:06,TACW242432G552,624F2732,624F2732,2025-01-23 15:29:06,2025-01-23 15:44:59,00:15:52,8.147,Local,2025-01-23 15:29:06=NoneA;2025-01-23 15:44:59=0A


.. _model_tags:

Tags
----

(RFID) tags are used by users to authorize charging by presenting them to the charger. The tag will then be validated by the CSMS/CS and 
charging will either be allowed to start, or rejected. :term:`balanz` may be configured to perform such authorization in which case the tags must
be present in a CSV file.

.. code-block:: text
    :caption: Example part of a `tags.csv` file

    id_tag,user_name,parent_id_tag,description,status,priority
    8A03EE96,Corp EV 1,ACME,Corporate tag for EV 1,Activated,1
    E08CEE18,Corp EV 2,ACME,Corporate tag for EV 2,Activated,1
    614C2776,Corp EV 3,ACME,Corporate tag for EV 3,Activated,1
    87DBF822,Corp EV 4,ACME,Corporate tag for EV 4,Activated,1
    DB08E534,Corp EV 5,ACME,Corporate tag for EV 5,Blocked,
    56EB8FBF,Christopher Moore,,Christopher Moore personal tag,Activated,
    FE7FF01E,Michael Miller,,Michael Miller (CEO) personal tag,Activated,10
    176A6AFA,David Davis,,David Davis (CFO) personal tag,Activated,10


The ``parent_id`` attribute is as defined by :term:`OCPP` and allows for any tag in the group identified by a ``parent_id_tag`` to terminate a
charging session.

Possible values for ``status`` are either ``Activated`` or ``Blocked``.

An optional ``priority`` value may overwrite the group priority.





















