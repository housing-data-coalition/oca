FROM python:3.6

COPY requirements.txt .

RUN apt-get update && \
  apt-get install -y \
    unzip \
    postgresql-client && \
  rm -rf /var/lib/apt/lists/*

RUN pip install -r requirements.txt

COPY . /app

WORKDIR /app

CMD ["python", "oca_update.py"]

ENV PATH /var/pydev/bin:$PATH
ENV PYTHONPATH /var/pydev
ENV PYTHONUNBUFFERED yup