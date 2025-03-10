# Makefile for Balanz project

BALANZ_VERSION=$(shell poetry version -s)

# OS specific stuff. Support both Windows and Linux
ifeq ($(OS), Windows_NT)
	copy=copy
	FixPath=$(subst /,\,$1)
	cmdsep=&
	IS_POETRY := $(shell pip freeze | find "poetry==")
	PLATFORM=Windows
else
	copy=cp
	FixPath=$1
	cmdsep=;
	IS_POETRY := $(shell pip freeze | grep "poetry==")
	PLATFORM=Linux
endif

.install-poetry:
ifndef IS_POETRY
	@echo Installing Poetry...
	pip install poetry
endif

format: .install-poetry
	poetry run isort balanz tests
	poetry run black balanz tests

model_dir=data/model
$(model_dir)/chargers.csv:
	@echo "Establishing chargers.csv file .."
	@$(copy) $(call FixPath,$(model_dir)/chargers-orig.csv) $(call FixPath,$(model_dir)/chargers.csv)

$(model_dir)/users.csv:
	@echo "Establishing users.csv file .."
	@$(copy) $(call FixPath,$(model_dir)/users-orig.csv) $(call FixPath,$(model_dir)/users.csv)

model_init: $(model_dir)/chargers.csv

update: .install-poetry
	poetry update

install: .install-poetry model_init
	poetry install

docker:
	@docker build -t balanz:latest .
	@docker tag balanz:latest balanz:$(BALANZ_VERSION)

docs: .install-poetry
	poetry run sphinx-build -b html docs/source docs/build

run: 
	cd data $(cmdsep) python $(call FixPath,../balanz/balanz.py)

test:
	$(MAKE) tests

