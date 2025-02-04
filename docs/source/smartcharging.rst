SmartCharging
=============

balanz focused on delivery Smart Charging by employing the balanz Smart Charging algorithm.  The algorithm is applied
to groups of chargers belonging to the same :ref:`allocation group <model-group>` which defines the overall allowed total allocation across
all chargers at a given point in time.

An allocation is also known as an offer, i.e. an offer to a charger that it *may* charge an attached EV with up to the
allocated/offered amount. balanz makes offers in units of Ampere (A) assumed to be made available across all 3 charger 
phases. 

Note: Allocation/offers are made in A. Assuming a Voltage of 230V, a 16A offer would equal 16A * 3 phases * 230V ~ 11kW.

balanz makes offers to Chargers using the following rules:

    - Offers are made in units of Ampere (A) and always in whole numbers.
    - Chargers without a connected EV or in a non-transactional state are not considered for offers, i.e. will have a Zero offer.
    - Offers are made according to priorities, coming from groups, tags, or possibly overwritten on a session basis.
    - At any point in time, the total offers across an :ref:`allocation group <model-group>` will not exceed the maximum defined. Note,
      that several maximum values may be set, both schedule- and priority dependent.
    - Offers are only made at or above a configured minimum defaulting to 6A. This is because some EVs will not charge below this level and
      may even enter an error state if offered less.
    - Initial offers will always be at the configured minimum (so default 6A).
    - Offers are considered unused if the maximum usage in the last period is less that a configured value (configurable, default 2A). 
      The period is configurable and defaults to 5 min.
    - Unused offers will be revoked after the configured period (default 5 min). The charger will be subject to receive an offer again after
      a configurable suspension time (default 1 hour). This mechanism is design to cater for situation where EV does not want to charge, either
      because it is set-up for delayed charging, or because it is full and has not yet terminated the session (aka charging transaction).
    - If the maximum usage in the last period is less than the offer by some margin (configurable, default 0.8A), the offer will be reduced
      to the first whole number of A higher than the maxium. This limit is seen to be associated with the EV (e.g. cannot charge at a higher
      rate than 16A) and so remains valid for the remainder of the session.
    - Initial offers are made under the same principle as unused offers described above.
    - Offers will increase at maximum (configurable, default 3A) in a step-wise fashon at the ealiest every defined period (configurable, 
      default 2 min). This ensure against too drastic fluxuations in the overall rebalancing process.


Charging Profiles
-----------------

(Smart)Charging in :term:`OCPP` is controlled by two calls, ``SetChargingProfile`` and ``ClearChargingProfile`` each with many different parameters
across three different profile types. balanz uses two such profile types, namely the default profile type ``TxDefaultProfile`` and the transaction 
specific profile type ``TxProfile``. Each profile has a priority defined by a so-called ``StackLevel`` parameter (0 being the lowest).

The ``SetChargingProfile`` call allows for specifying advanced schedules. balanz uses no schedules, but always asks that changes be immediate - 
and valid forever/until changed again.

When a charger connects to balanz, it will ensure the creation of  two ``TxDefaultProfile``s. The first *minimum profile* (with ``StackLevel`` 0) 
will be set to the miniumum charging offer (default 6A) while the second *blocking profile* (with ``StackLevel`` 1) will be configured with 
no (i.e. zero) allocation. This profile ensures that a charger cannot start using until and unless balanz has specifically made a charging offer.

When an EV charging sesison starts - typically as a result of scanning an RFID tag - the *blocking profile* will cause the charger to enter
the ``SuspendedEVSE`` state. This state indicates that no offer can be made by the charger. balanz will then quickly (subject to availability
and priority) make an offer to the charger by deleting the *blocking profile* (the one with a zero allocation) thus exposing the *minimum profile*.
This allows a transaction to start with the minimum offer presented by the first profile (6A).

All subsequent changes to offers/allocations will be made by setting a ``TxProfile``. This has the advantage that such offer will automatically
be invalidated once a transaction stops. The first time a `TxProfile` setting is done for a transaction, balanz will restore *blocking profile*
in order to be ready for the next charging session.


Delayed Charging
----------------

An important topic for EV charging is the concept of Delayed Charging where the EV is instructed to delay start of charging until a certain time,
e.g. at midnight. This is typically done to ensure that charging happens when prices are low. Delay of charging can also be set via Apps that
sync with the EV.

When the time of charging is reached, charging will start provided that there is an actual offer available from the charger. If no offer is 
available, charging will not start. What happens from here depends on the brand of EV. In some cases, charging will start when an offer is 
made (balanz could e.g. be setup to made offers once every hour), while other EVs will simply never start charging in that session!

balanz includes some measures to deal with delayed charging, but in general it is recommended to turn off delayed charging and leave all
Smart Charging decisions to balanz.


Charging priority
-----------------

Power will be allocated by prority (higher is better). The priority for a connnector on a charger will take its default from a containing
group, but can be overwritten by a priority associated with the tag used to start the session, or even further overwritten per charging
session (transaction) using a specific API call.

Besides prioritizing allocation between charging sessions, priority values also define if a given total allocation may be extended closer
to the actual maximum. In this way, higher priority sesssions be allowed to charge at a higher rate than would otherwise be the case 
(typically at expensive times.)

Reviewing a session from a group:

.. code-block::
    :caption: Example `groups.csv` file

    group_id,parent_id,description,priority,max_allocation
    HQ,ACME,HQ site,,00:00-07:59>0=63;08:00-16:59>0=20:3=63;17:00-20:59>5=63;21:00-23:59>0=40:3=63
