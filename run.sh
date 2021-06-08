# make this executable by running: chmod a+x run.sh
open -a Docker
docker compose up  \
    --abort-on-container-exit \
    --exit-code-from app
