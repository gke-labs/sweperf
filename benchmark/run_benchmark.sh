#!/bin/bash
set -eo pipefail

CONCURRENCY=${1:-5}
TOTAL_PODS=${2:-20}
BENCHMARK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_FILE="$BENCHMARK_DIR/../generated_images.txt"

if [ ! -f "$IMAGE_FILE" ]; then
    echo "Error: $IMAGE_FILE not found. Did you run setup.sh?"
    exit 1
fi

# Read all images into an array (ignoring empty lines)
mapfile -t IMAGES < <(grep -v '^$' "$IMAGE_FILE")
NUM_IMAGES=${#IMAGES[@]}

if [ "$NUM_IMAGES" -eq 0 ]; then
    echo "Error: No images found in $IMAGE_FILE."
    exit 1
fi

echo "=== Generating ClusterLoader2 Configuration ==="
echo "Total Pods: $TOTAL_PODS"
echo "Target Concurrency: $CONCURRENCY"
echo "Unique Images: $NUM_IMAGES"

# Generate config.yaml for ClusterLoader2
cat <<EOF > "$BENCHMARK_DIR/config.yaml"
name: swebench-load
namespace:
  number: 1
tuningSets:
- name: FixedConcurrencyTuningSet
  parallelismLimitedLoad:
    parallelismLimit: $CONCURRENCY
steps:
- name: Submit SWE-bench Pods
  phases:
EOF

PODS_PER_IMAGE=$(( TOTAL_PODS / NUM_IMAGES ))
REMAINDER=$(( TOTAL_PODS % NUM_IMAGES ))

# We will create a distinct phase and pod template for each image
for i in "${!IMAGES[@]}"; do
    IMAGE="${IMAGES[$i]}"
    COUNT=$PODS_PER_IMAGE
    
    # Distribute any remainder to the first few images
    if [ "$i" -lt "$REMAINDER" ]; then
        COUNT=$((COUNT + 1))
    fi
    
    if [ "$COUNT" -gt 0 ]; then
        POD_TEMPLATE="$BENCHMARK_DIR/pod_template_${i}.yaml"
        # ClusterLoader2 uses {{.Name}} to dynamically generate unique names
        cat <<PODEOF > "$POD_TEMPLATE"
apiVersion: v1
kind: Pod
metadata:
  name: {{.Name}}
spec:
  restartPolicy: Never
  containers:
  - name: swebench
    image: $IMAGE
    env:
    - name: LLM_LATENCY_MU
      value: "2.0414"
    - name: LLM_LATENCY_SIGMA
      value: "0.8674"

PODEOF

        cat <<EOF >> "$BENCHMARK_DIR/config.yaml"
  - namespaceRange:
      min: 1
      max: 1
    replicasPerNamespace: $COUNT
    tuningSet: FixedConcurrencyTuningSet
    objectBundle:
    - basename: swebench-${i}
      objectTemplatePath: pod_template_${i}.yaml
EOF
    fi
done

echo "Configuration generated at $BENCHMARK_DIR/config.yaml"

# Ensure we have ClusterLoader2
if [ ! -d "$BENCHMARK_DIR/perf-tests" ]; then
    echo "=== Cloning kubernetes/perf-tests for ClusterLoader2 ==="
    git clone https://github.com/kubernetes/perf-tests.git "$BENCHMARK_DIR/perf-tests"
fi

echo "=== Running ClusterLoader2 ==="
cd "$BENCHMARK_DIR/perf-tests/clusterloader2"

# Ensure Go is available. If not, this step will fail.
if ! command -v go &> /dev/null; then
    echo "Error: 'go' is not installed. ClusterLoader2 requires Go to run."
    exit 1
fi

# Run the benchmark
go run cmd/clusterloader.go \
    --kubeconfig="$HOME/.kube/config" \
    --testconfig="$BENCHMARK_DIR/config.yaml" \
    --provider=gke \
    --v=2

echo "=== Benchmark execution complete! ==="
