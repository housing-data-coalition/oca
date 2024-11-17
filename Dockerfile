FROM python:3.11.4
ENV TZ=America/New_York

# Update package lists
RUN apt-get update 

# Setup Python
RUN apt-get install -y python3 python3-pip
COPY requirements.txt .
RUN pip install -r requirements.txt

# Setup PostgresSQL and clean up
RUN apt-get install -y \
    unzip \
    curl \
    postgresql-client && \
  rm -rf /var/lib/apt/lists/*

# Check the latest version here https://www.nyc.gov/site/planning/data-maps/open-data/dwn-gdelx.page
# Copy the link to see the verison numbers
# Example: https://s-media.nyc.gov/agencies/dcp/assets/files/zip/data-tools/bytes/linux_geo24c_24.3.zip
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
ENV RELEASE=24c
ENV MAJOR=24
ENV MINOR=3
ENV PATCH=0
WORKDIR /geosupport

RUN  pip install python-geosupport; \
    FILE_NAME=linux_geo${RELEASE}_${MAJOR}.${MINOR}.zip; \
    echo ${FILE_NAME}; \
    curl -O https://s-media.nyc.gov/agencies/dcp/assets/files/zip/data-tools/bytes/$FILE_NAME; \
    unzip *.zip; \
    rm *.zip; 

ENV GEOFILES=/geosupport/version-${RELEASE}_${MAJOR}.${MINOR}/fls/
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/geosupport/version-${RELEASE}_${MAJOR}.${MINOR}/lib/

# Create ssh folder
RUN mkdir -p ~/.ssh && chmod 0700 ~/.ssh 

COPY . /app

WORKDIR /app

CMD ["python", "oca_update.py"]

ENV PATH /var/pydev/bin:$PATH
ENV PYTHONPATH /var/pydev
ENV PYTHONUNBUFFERED 1