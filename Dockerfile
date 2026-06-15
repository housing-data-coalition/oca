ARG TARGETPLATFORM=linux/amd64
FROM --platform=$TARGETPLATFORM python:3.12.13-slim-trixie
ENV TZ=America/New_York

# Update package lists
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    openssh-client curl ca-certificates unzip && \
    rm -rf /var/lib/apt/lists/*
# Check the latest version of Geosupport Desktop Edition™ - Linux version
# at https://www.nyc.gov/content/planning/pages/resources/geocoding/geosupport-desktop-edition
# Example: https://s-media.nyc.gov/agencies/dcp/assets/files/zip/data-tools/bytes/geosupport/linux_geo25A1_25.11.zip
# In the script set if statement under the comment '# setup pluto if it does not exist' to True
# 
# To manually update:
# Upload pluto.csv to s3 and run ./lib/sql/create_pluto_table.sql, Then
# SELECT aws_s3.table_import_from_s3(
# 'pluto', '', '(FORMAT CSV, HEADER)',
# aws_commons.create_s3_uri('oca-2-dev', 'public/pluto.csv', 'us-east-1'),
# aws_commons.create_aws_credentials('id', 'key', '')
# );
# Lastly alter_pluto_table.sql
ENV RELEASE=25A1
ENV MAJOR=25
ENV MINOR=11
WORKDIR /geosupport

RUN FILE_NAME=linux_geo${RELEASE}_${MAJOR}.${MINOR}.zip; \
    echo ${FILE_NAME}; \
    curl -O https://s-media.nyc.gov/agencies/dcp/assets/files/zip/data-tools/bytes/geosupport/$FILE_NAME; \
    unzip *.zip; \
    rm *.zip; \
    ACTUAL_FOLDER=$(ls -d version-* | head -1); \
    ln -s "$ACTUAL_FOLDER" current_version

# Copy app and create virtual environment.
# Use pip (not uv) for dependency install: uv's native binary segfaults under
# QEMU when building linux/amd64 images on Apple Silicon.
COPY pyproject.toml /app/
WORKDIR /app
RUN python -m venv /app/.venv && \
    /app/.venv/bin/pip install --no-cache-dir --upgrade pip && \
    python3 -c "import tomllib; deps=tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']; open('requirements.txt','w').write('\n'.join(deps))" && \
    /app/.venv/bin/pip install --no-cache-dir -r requirements.txt
COPY . /app

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV GEOFILES=/geosupport/current_version/fls/
ENV LD_LIBRARY_PATH=/geosupport/current_version/lib/

# Create ssh folder
RUN mkdir -p ~/.ssh && chmod 0700 ~/.ssh 

WORKDIR /app
CMD ["python", "oca_update.py"]