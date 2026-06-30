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



# 1. Pre-pull SWE-bench image to target nodes
echo "Pre-pulling SWE-bench image: $SWE_BENCH_IMAGE to cluster..."
chmod +x "$(dirname "$0")/prepull_images.py"
"$(dirname "$0")/prepull_images.py" "$SWE_BENCH_IMAGE"

echo "=== Done! ==="
echo "=== Done! ==="
echo "Image Pre-pulled: $SWE_BENCH_IMAGE"
