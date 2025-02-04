FROM python:3-slim

# Set default port
EXPOSE 9999

# Set the working directory in the container
WORKDIR /app

# Python
ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100

# Poetry
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_CACHE_DIR='/var/cache/pypoetry' \
    POETRY_HOME='/usr/local' \
    POETRY_PACKAGE_MODE=

# poetry and dependencies
RUN pip install poetry
COPY pyproject.toml poetry.lock /app/
RUN poetry install --no-ansi --only=main --no-root

# Code
COPY balanz/*.py /app

# Run app.py when the container launches
CMD ["python", "balanz.py"]
