#!/bin/bash
set -eo pipefail

PROJECT_ID=$1
REGION=$2
CLUSTER_NAME=$3
BUCKET_NAME=$4
REPO_NAME=$5
shift 5
IMAGES=("$@")

if [ -z "$REPO_NAME" ]; then
    echo "Usage: $0 <PROJECT_ID> <REGION> <CLUSTER_NAME> <BUCKET_NAME> <REPO_NAME> [SWE_BENCH_IMAGES...]"
    echo "Example: $0 my-project us-central1 my-cluster my-swe-bucket my-repo swebench/sweb.eval.x86_64.astropy_1776_astropy-12907"
    exit 1
fi

if [ ${#IMAGES[@]} -eq 0 ]; then
    IMAGES=("swebench/sweb.eval.x86_64.astropy_1776_astropy-12907") # Default fallback
fi

echo "=== 1. Creating GKE Cluster ==="
gcloud container clusters create "$CLUSTER_NAME" \
    --project="$PROJECT_ID" \
    --zone="${REGION}-a" \
    --machine-type="c4-standard-16" \
    --disk-size="500GB" \
    --disk-type="pd-balanced" \
    --num-nodes=2 \
    --scopes="gke-default,storage-rw" || echo "Cluster may already exist or failed to create."
gcloud container clusters get-credentials "$CLUSTER_NAME" --zone="${REGION}-a" --project="$PROJECT_ID"

echo "=== 2. Creating GCS Bucket ==="
gcloud storage buckets create "gs://$BUCKET_NAME" --project="$PROJECT_ID" --location="$REGION" || echo "Bucket may already exist."

echo "=== 3. Creating Artifact Registry Repo ==="
gcloud artifacts repositories create "$REPO_NAME" \
    --repository-format=docker \
    --location="$REGION" \
    --project="$PROJECT_ID" || echo "Repo may already exist."

gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet

echo "=== 4. Extracting SWE-bench Data & Building Base Image ==="
for IMAGE in "${IMAGES[@]}"; do
    echo "Processing $IMAGE..."
    docker pull "$IMAGE"
    CONTAINER_ID=$(docker create "$IMAGE")
    TEMP_DIR=$(mktemp -d)

    # Ensure extraction paths exist in case the SWE-bench image layout differs slightly
    docker cp "$CONTAINER_ID:/testbed" "$TEMP_DIR/testbed" || echo "/testbed not found, skipping."
    docker cp "$CONTAINER_ID:/opt/miniconda3" "$TEMP_DIR/miniconda3" || echo "/opt/miniconda3 not found, skipping."

    IMAGE_CLEAN=$(echo "$IMAGE" | tr '/:' '_')
    TARBALL_NAME="${IMAGE_CLEAN}.tar"

    echo "Creating tarball $TARBALL_NAME..."
    # Go to TEMP_DIR so we package from root of these folders
    tar -cf "$TARBALL_NAME" -C "$TEMP_DIR" .

    echo "Uploading to GCS..."
    gcloud storage cp "$TARBALL_NAME" "gs://$BUCKET_NAME/$TARBALL_NAME"

    rm "$TARBALL_NAME"
    rm -rf "$TEMP_DIR"
    docker rm "$CONTAINER_ID"
done

echo "Building base Sandbox image..."
BASE_IMAGE_TAG="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/swe-bench-base:latest"
cat <<EOF > Dockerfile.base
FROM python:3.10-slim
RUN apt-get update && apt-get install -y curl tar && rm -rf /var/lib/apt/lists/*
EOF
docker build -t "$BASE_IMAGE_TAG" -f Dockerfile.base .
rm Dockerfile.base
docker push "$BASE_IMAGE_TAG"

echo "=== 5. Installing Agent Sandbox ==="
# Clone fresh to avoid version creep
AGENT_SANDBOX_DIR=$(mktemp -d)
echo "Cloning fresh agent-sandbox repository to $AGENT_SANDBOX_DIR..."
git clone https://github.com/kubernetes-sigs/agent-sandbox.git "$AGENT_SANDBOX_DIR"

cd "$AGENT_SANDBOX_DIR"

IMAGE_PREFIX="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/"
echo "Building Agent Sandbox controller and pushing to $IMAGE_PREFIX"
./dev/tools/push-images --image-prefix="$IMAGE_PREFIX" --controller-only

echo "Deploying to Kubernetes cluster"
./dev/tools/deploy-to-kube --image-prefix="$IMAGE_PREFIX" --extensions

# Clean up temporary clone
cd - > /dev/null
rm -rf "$AGENT_SANDBOX_DIR"

echo "=== Done! Setup Complete. ==="
echo "Cluster: $CLUSTER_NAME"
echo "Bucket: gs://$BUCKET_NAME"
echo "Base Image: $BASE_IMAGE_TAG"
