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
    --disk-type="hyperdisk-balanced" \
    --num-nodes=2 \
    --scopes="gke-default,storage-rw"
gcloud container clusters get-credentials "$CLUSTER_NAME" --zone="${REGION}-a" --project="$PROJECT_ID"

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

echo "=== 6. Pre-pulling SWE-bench Images to Target Nodes ==="
# Make sure prepull_images.py is executable
chmod +x "$(dirname "$0")/prepull_images.py"
"$(dirname "$0")/prepull_images.py" "${IMAGES[@]}"

echo "=== Done! Setup Complete. ==="
echo "Cluster: $CLUSTER_NAME"
