#!/bin/bash
set -eo pipefail

PROJECT_ID=$1
REGION=$2
CLUSTER_NAME=$3
REPO_NAME=$4
shift 4
LIMIT=${1:-5}

if [ -z "$REPO_NAME" ]; then
    echo "Usage: $0 <PROJECT_ID> <REGION> <CLUSTER_NAME> <REPO_NAME> [LIMIT]"
    echo "Example: $0 my-project us-central1 my-cluster my-repo 5"
    exit 1
fi
echo "=== 1. Creating GKE Cluster ==="
gcloud container clusters create "$CLUSTER_NAME" \
    --project="$PROJECT_ID" \
    --zone="${REGION}-b" \
    --machine-type="c4-standard-16" \
    --disk-size="500GB" \
    --disk-type="hyperdisk-balanced" \
    --num-nodes=3 \
    --default-max-pods-per-node=256 \
    --scopes="gke-default,storage-rw" || echo "Cluster may already exist."
gcloud container clusters get-credentials "$CLUSTER_NAME" --zone="${REGION}-b" --project="$PROJECT_ID"

echo "Waiting for cluster API to become reachable..."
for i in {1..10}; do
    if kubectl get nodes; then
        echo "Cluster is reachable."
        break
    fi
    echo "Waiting for cluster... ($i/10)"
    sleep 15
done

echo "=== 3. Creating Artifact Registry Repo ==="
gcloud artifacts repositories create "$REPO_NAME" \
    --repository-format=docker \
    --location="$REGION" \
    --project="$PROJECT_ID" || echo "Repo may already exist."

gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet

echo "=== 4. Granting GKE nodes access to Artifact Registry ==="
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
gcloud artifacts repositories add-iam-policy-binding "$REPO_NAME" \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/artifactregistry.reader"

echo "=== 5. Generating and Pushing Test Images ==="
IMAGE_PREFIX="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/"
GENERATED_IMAGES_FILE="$(pwd)/generated_images.txt"

# Ensure virtual environment exists and activate it
VENV_DIR="$(dirname "$0")/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

pip install -i https://pypi.org/simple -r "$(dirname "$0")/generate-images/requirements.txt"
GENERATED_YAML_FILE="$(pwd)/generated_images.yaml"
python3 "$(dirname "$0")/generate-images/generate.py" --build --push --image-prefix "$IMAGE_PREFIX" --output-list "$GENERATED_IMAGES_FILE" --output-yaml "$GENERATED_YAML_FILE" --limit "$LIMIT"

echo "=== 6. Installing Agent Sandbox ==="
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

echo "=== 7. Pre-pulling SWE-bench Images to Target Nodes ==="
# Make sure prepull_images.py is executable
chmod +x "$(dirname "$0")/prepull_images.py"
if [ -f "$GENERATED_IMAGES_FILE" ]; then
    "$(dirname "$0")/prepull_images.py" --image-file "$GENERATED_IMAGES_FILE"
else
    echo "Warning: $GENERATED_IMAGES_FILE not found, skipping prepull."
fi

echo "=== Done! Setup Complete. ==="
echo "Cluster: $CLUSTER_NAME"
