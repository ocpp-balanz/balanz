# balanz tests

**WARNING: TESTS ARE VERY MUCH NOT COMPLETE**

This directory contains balanz test scripts. Most scripts are pytest-based scripts that interact with
[ocppsim](https://github.com/ocpp-balanz/ocppsim), the OCPP simulator created for this very purpose.

Note: For now, the tests assume that `balanz` is available in CSMS/CS mode with smart charging enabled.
The configuration and model contained in the `data` directory are used for the tests. Initially,
the startup of `ocpp` instances is also assumed - may be automated later.

A windows script `ocpp_start.bat` may be used to start the instances.

## A note on timing

The tests take a VERY long time to run as their rely on the standard timings. An alternative would have
been to manipulate the clock logic to speed things up, but the risk that it would not correctly cover
the intended functional test was simply too great.

So, start the tests and do something else while they run!

Warning: To be honest, the timings typically make the pytest runs fail. So, for now, the best way is
to run them using the "trick" described at the start of the test files and run with `python`.

## Testing single charger - normal operations

Simple tests covered by test_single.py. Assumings running `ocpp` instance mimicing charger `TACW225426G463`
listening on the default websocket command interface port (1234) on localhost connected to a running balanz
full CS instance.

## balanz across multiple chargers

The model included below `data` will be used. The following chargers will be used (from `data/chargers.csv`).
They are all from the `RR2` site as this importantly has a constant schedule throughout the day. Otherwise
it would be a nightmare to run tests (they would behave differently at different times of the day!)

```text
charger_id,alias,group_id,no_connectors,description,conn_max,auth_sha
TACW224317G584,RR2-01,RR2-HIGH,1,RR2 charger RR2-01,32.0,
TACW224137G670,RR2-02,RR2-LOW,1,RR2 charger RR2-02,32.0,
TACW224537G682,RR2-03,RR2-LOW,1,RR2 charger RR2-03 (limit 16A),16.0,
TACW223437G682,RR2-04,RR2-LOW,1,RR2 charger RR2-04 (limit 8A),8.0,
```

The tests assume `ocpp` instances to be available for these four chargers with command interfaces as follows:

Charger        | Charger Alias | Websocket port for command interface
---------------|---------------|----------------------
TACW224317G584 | RR2-01        | 1235
TACW224137G670 | RR2-02        | 1236
TACW224537G682 | RR2-03        | 1237
TACW223437G682 | RR2-04        | 1238

The group definitions are as per definition in `data/model`.

