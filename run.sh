#!/bin/bash

# make this executable by running: chmod a+x run.sh

open -a Docker

while (! docker stats --no-stream ); do
  # Docker takes a few seconds to initialize
  echo "Waiting for Docker to launch..."
  sleep 10
done

docker-compose build && \
  docker-compose up  \
    --abort-on-container-exit \
    --exit-code-from app
