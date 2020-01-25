FROM python:3.6

# Setup Python
COPY requirements.txt .
RUN pip install -r requirements.txt

# Setup PostgresSQL
RUN apt-get update && \
  apt-get install -y \
    unzip \
    postgresql-client && \
  rm -rf /var/lib/apt/lists/*

# Authorize SSH Host for SFTP connection
ARG SFTP_HOST
RUN mkdir -p /root/.ssh && \
    chmod 0700 /root/.ssh && \
    ssh-keyscan -t dsa ${SFTP_HOST} >> /root/.ssh/known_hosts

COPY . /app

WORKDIR /app

CMD ["python", "oca_update.py"]

ENV PATH /var/pydev/bin:$PATH
ENV PYTHONPATH /var/pydev
ENV PYTHONUNBUFFERED yup