#!/bin/bash
set -eo pipefail

# --- Configuration ---
DOCKER_USER="justfix"
DOCKER_TEAM="justfixnyc"
REPO_NAME="oca"
IMAGE_TAG="${1:-latest}"
PLATFORM="${DOCKER_PLATFORM:-linux/amd64}"

FULL_IMAGE_NAME="${DOCKER_TEAM}/${REPO_NAME}:${IMAGE_TAG}"
DOCKERFILE_PATH="./Dockerfile"

# Ensure credentials are set as environment variables for security
if [ -z "$DOCKER_PASSWORD" ]; then
  echo "Error: DOCKER_PASSWORD environment variable not set."
  exit 1
fi
# ---------------------

echo "Starting Docker image build and push process..."
echo "Platform: ${PLATFORM}"
echo "Image: ${FULL_IMAGE_NAME}"

# 1. Log in to Docker Hub using standard input for the password for security
echo "Logging in to Docker Hub..."
echo "$DOCKER_PASSWORD" | docker login --username "$DOCKER_USER" --password-stdin
if [ $? -ne 0 ]; then
  echo "Error: Docker login failed."
  exit 1
fi
echo "Successfully logged in."

# 2. Ensure a buildx builder is available (needed for cross-platform builds on Apple Silicon)
if ! docker buildx inspect >/dev/null 2>&1; then
  echo "Creating buildx builder oca-builder..."
  docker buildx create --use --name oca-builder
fi

# 3. Build and push the image (linux/amd64 for K8s / Geosupport)
echo "Building and pushing image: ${FULL_IMAGE_NAME} from ${DOCKERFILE_PATH}..."
docker buildx build \
  --platform "${PLATFORM}" \
  -f "${DOCKERFILE_PATH}" \
  -t "${FULL_IMAGE_NAME}" \
  --push \
  .
if [ $? -ne 0 ]; then
  echo "Error: Docker build/push failed."
  exit 1
fi
echo "Successfully built and pushed image to Docker Hub."

# Optional: Log out of Docker Hub after pushing
docker logout
echo "Logged out of Docker Hub."
