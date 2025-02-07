# OS specific stuff. Support both Windows and Linux
ifeq ($(OS), Windows_NT)
	CWD := $(shell echo %CD%)
	cmdsep=&
	PLATFORM := Windows
else
	CWD := $(shell pwd)
	cmdsep=;
	PLATFORM := Linux
endif


SIMPATH := ../../ocppsim
SIMCMD := python ocppsim.py

test_single:
	pytest test_single.py



