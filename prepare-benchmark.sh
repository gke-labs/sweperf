#!/bin/bash
set -eo pipefail

PROJECT_ID=$1
REGION=$2
BUCKET_NAME=$3
REPO_NAME=$4
SWE_BENCH_IMAGE="swebench/sweb.eval.x86_64.astropy__astropy-12907" # Default or passed as argument

if [ "$#" -lt 4 ]; then
    echo "Usage: $0 <PROJECT_ID> <REGION> <BUCKET_NAME> <REPO_NAME> [SWE_BENCH_IMAGE]"
    echo "Example: $0 my-gcp-project us-central1 my-swe-bench-bucket agentic-bench-repo"
    exit 1
fi

if [ -n "$5" ]; then
    SWE_BENCH_IMAGE=$5
fi

echo "=== Preparing Benchmark Infrastructure ==="

# 1. Create GCS Bucket
echo "Creating GCS Bucket: $BUCKET_NAME in $REGION..."
gcloud storage buckets create "gs://$BUCKET_NAME" --project="$PROJECT_ID" --location="$REGION" || echo "Bucket may already exist, proceeding."

# 2. Create Artifact Registry Repo
echo "Creating Artifact Registry Repo: $REPO_NAME in $REGION..."
gcloud artifacts repositories create "$REPO_NAME" \
    --repository-format=docker \
    --location="$REGION" \
    --project="$PROJECT_ID" || echo "Repo may already exist, proceeding."

# 3. Pull SWE-bench image and extract data
echo "Pulling SWE-bench image: $SWE_BENCH_IMAGE..."
docker pull "$SWE_BENCH_IMAGE"

echo "Extracting data from SWE-bench image..."
CONTAINER_ID=$(docker create "$SWE_BENCH_IMAGE")
TEMP_DIR=$(mktemp -d)

# Ensure extraction paths exist in case the SWE-bench image layout differs slightly
docker cp "$CONTAINER_ID:/testbed" "$TEMP_DIR/testbed" || echo "/testbed not found, skipping."
docker cp "$CONTAINER_ID:/opt/miniconda3" "$TEMP_DIR/miniconda3" || echo "/opt/miniconda3 not found, skipping."

IMAGE_CLEAN=$(echo "$SWE_BENCH_IMAGE" | tr '/:' '_')
TARBALL_NAME="${IMAGE_CLEAN}.tar"

echo "Creating tarball: $TARBALL_NAME..."
tar -cf "$TARBALL_NAME" -C "$TEMP_DIR" .

echo "Uploading tarball to GCS..."
gsutil cp "$TARBALL_NAME" "gs://$BUCKET_NAME/$TARBALL_NAME"

echo "Cleaning up tarball and container..."
rm "$TARBALL_NAME"
rm -rf "$TEMP_DIR"
docker rm "$CONTAINER_ID"

# 4. Build and push base image
echo "Building base image..."
BASE_IMAGE_TAG="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/swe-bench-base:latest"
cat <<EOF > Dockerfile.base
FROM python:3.10-slim
RUN apt-get update && apt-get install -y curl tar && rm -rf /var/lib/apt/lists/*
EOF

docker build -t "$BASE_IMAGE_TAG" -f Dockerfile.base .
rm Dockerfile.base

echo "Pushing base image to Artifact Registry..."
# Authenticate docker to AR
gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet
docker push "$BASE_IMAGE_TAG"

echo "=== Done! ==="
echo "Bucket URL: gs://$BUCKET_NAME"
echo "Tarball: gs://$BUCKET_NAME/$TARBALL_NAME"
echo "Base Image: $BASE_IMAGE_TAG"
