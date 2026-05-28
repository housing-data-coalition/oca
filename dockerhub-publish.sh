#!/bin/bash
set -eo pipefail

# --- Configuration ---
DOCKER_USER="justfix"
DOCKER_TEAM="justfixnyc"
REPO_NAME="oca"
IMAGE_TAG="latest" # Or use a dynamic tag like $1 or a version number

FULL_IMAGE_NAME="${DOCKER_TEAM}/${REPO_NAME}:${IMAGE_TAG}"
DOCKERFILE_PATH="./Dockerfile" # Path to your Dockerfile

# Ensure credentials are set as environment variables for security
if [ -z "$DOCKER_PASSWORD" ]; then
  echo "Error: DOCKER_PASSWORD environment variable not set."
  exit 1
fi
# ---------------------

echo "Starting Docker image build and push process..."

# 1. Log in to Docker Hub using standard input for the password for security
echo "Logging in to Docker Hub..."
echo "$DOCKER_PASSWORD" | docker login --username "$DOCKER_USER" --password-stdin
if [ $? -ne 0 ]; then
  echo "Error: Docker login failed."
  exit 1
fi
echo "Successfully logged in."

# 2. Build the Docker image
echo "Building image: ${FULL_IMAGE_NAME} from ${DOCKERFILE_PATH}..."
docker build -f "${DOCKERFILE_PATH}" -t "${FULL_IMAGE_NAME}" .
if [ $? -ne 0 ]; then
  echo "Error: Docker build failed."
  exit 1
fi
echo "Successfully built image."

# 3. Push the image to Docker Hub
echo "Pushing image: ${FULL_IMAGE_NAME} to Docker Hub..."
docker push "${FULL_IMAGE_NAME}"
if [ $? -ne 0 ]; then
  echo "Error: Docker push failed."
  exit 1
fi
echo "Successfully pushed image to Docker Hub."

# Optional: Log out of Docker Hub after pushing
docker logout
echo "Logged out of Docker Hub."
