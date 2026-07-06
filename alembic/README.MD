HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose -f storage-docker-compose.yml run --rm  content-processing-migrate \
  alembic -n content_processing revision --autogenerate -m "create youtube jobs"