Introduction
============

:term:`balanz` originates from an specific need to control power allocation across a set of chargers sharing the same electrical supply. 
It is critical that the combined power consumption of all chargers never exceeds the available supply - otherwise fuses may blow or other issues arise.

Allocation of maximum power that chargers may deliver to connected Electric Vechiles (EVs) may be controlled programmatically via the Open Charge Point Protocol (OCPP) standard.

The goal of :term:`balanz` is to provide a simple and efficient way to manage charging sessions, ensuring that each charger receives its fair share of power while 
not overloading the electrical supply. Such functionality is known as Smart Charging.

As per :term:`OCPP` standard Smart Charging may be embedded in the Charging Station Management System (:term:`CSMS`), also sometimes referred to simply as the Central System (CS) or, alternatively,
as a separate Local Controller (:term:`LC`) component. :term:`balanz` supports both :term:`CS` and :term:`LC` modes of operation.

:term:`OCPP` defines an :term:`LC` as follows:

    Optional device in a smart charging infrastructure. Located on the premises with a number of Charge Points
    connected to it. Sits between the Charge Points and Central System. Understands and speaks OCPP
    messages. Controls the Power or Current in other Charge Point by using OCPP smart charging messages. Can
    be a Charge Point itself.

If deployed as a :term:`LC`, :term:`balanz` will rely on a :term:`CSMS`/:term:`CS` for all charger operations not related to Smart Charging, including things like session authorization, reporting, firmware upgrades, etc. 
The :term:`CSMS`/:term:`CS` in this case will likely be supplied by the manufacturer of the chargers, but could even be a third-party provider.

While not the primary focus, it is possible to deploy :term:`balanz` without enabling Smart Charging. In this case, :term:`balanz` would either work as an OCPP-proxy (:term:`LC` mode), or
as a full (simple) - :term:`CSMS`/:term:`CS`.

Below diagram shows different :term:`balanz` deployment options.

.. code-block:: text

 EV <--> Charger <-- OCPP --> balanz LC (w/Smart Charging) <-- OCPP --> CSMS/CS
 EV <--> Charger <-- OCPP --> balanz CSMS/CS (w/Smart Charging)
 EV <--> Charger <-- OCPP --> balanz LC (wo/Smart Charging) <-- OCPP --> CSMS/CS
 EV <--> Charger <-- OCPP --> balanz CSMS/CS (wo/Smart Charging)


:term:`balanz` supports :term:`OCPP-J` v1.6.

:term:`balanz` is a python application based on the brilliant `occp library <https://github.com/mobilityhouse/ocpp>`_ kindly provided using an MIT license by 
`MobilityHouse <https://www.mobilityhouse.com/>`_.

The :term:`balanz` project is hosted at `GitHub <https://github.com/ocpp-balanz/>`_ and is covered by an MIT license.
