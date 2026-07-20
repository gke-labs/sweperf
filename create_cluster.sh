PROJECT_ID=bsalmon-gke-dev
REGION=us-central1
CLUSTER_NAME=sweperf-cluster-2
REPO_NAME=sweperf-july18

gcloud container clusters create "$CLUSTER_NAME" \
    --project="$PROJECT_ID" \
    --zone="${REGION}-b" \
    --machine-type="c4-highmem-16" \
    --disk-size="500GB" \
    --disk-type="hyperdisk-balanced" \
    --num-nodes=3 \
    --default-max-pods-per-node=256 \
    --enable-ip-alias \
    --scopes="gke-default,storage-rw" || echo "Cluster may already exist"

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
gcloud artifacts repositories add-iam-policy-binding "$REPO_NAME" \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/artifactregistry.reader"

gcloud container clusters get-credentials "$CLUSTER_NAME" --zone="${REGION}-b" --project="$PROJECT_ID"
