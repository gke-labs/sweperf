#!/bin/bash
set -e

if [ "$#" -ne 4 ]; then
    echo "Usage: $0 <pod_template.yaml> <concurrency> <total_pods> <images_file>"
    exit 1
fi

TEMPLATE=$1
CONCURRENCY=$2
TOTAL=$3
IMAGES_FILE=$4

if [ ! -f "$TEMPLATE" ]; then
    echo "Error: Template file $TEMPLATE not found."
    exit 1
fi

if [ ! -f "$IMAGES_FILE" ]; then
    echo "Error: Images file $IMAGES_FILE not found."
    exit 1
fi

mapfile -t IMAGES < <(grep -v '^$' "$IMAGES_FILE")
NUM_IMAGES=${#IMAGES[@]}

if [ "$NUM_IMAGES" -eq 0 ]; then
    echo "Error: No images found in $IMAGES_FILE."
    exit 1
fi

echo "=== SWE-bench Custom Submitter ==="
echo "Concurrency: $CONCURRENCY"
echo "Total Pods: $TOTAL"
echo "Unique Images: $NUM_IMAGES"
echo "----------------------------------"

run_pod() {
    local idx=$1
    local rand_idx=$(( RANDOM % NUM_IMAGES ))
    local image="${IMAGES[$rand_idx]}"
    local pod_name="swebench-run-${idx}-$RANDOM"

    echo "[Pod $pod_name] Submitting with image: $image"

    # Replace placeholders and apply to cluster
    sed -e "s|{{IMAGE}}|$image|g" -e "s|{{NAME}}|$pod_name|g" "$TEMPLATE" | kubectl apply -f - > /dev/null

    # Wait for the pod to finish (Succeeded or Failed)
    while true; do
        # We redirect stderr to null to avoid noisy error logs if the pod doesn't exist yet
        phase=$(kubectl get pod "$pod_name" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
        
        if [[ "$phase" == "Succeeded" ]]; then
            echo "[Pod $pod_name] Finished successfully."
            break
        elif [[ "$phase" == "Failed" ]]; then
            echo "[Pod $pod_name] Failed."
            break
        fi
        sleep 5
    done
    
    # We can delete it afterwards to keep the cluster clean, but we'll leave it 
    # for debugging purposes for now.
    # kubectl delete pod "$pod_name" > /dev/null 2>&1
}

# Main event loop
for (( i=1; i<=TOTAL; i++ )); do
    # If we have reached our concurrency limit, wait for any background job to finish
    while [[ $(jobs -r -p | wc -l) -ge $CONCURRENCY ]]; do
        wait -n
    done

    # Launch the next pod in the background
    run_pod "$i" &
done

echo "All tasks submitted. Waiting for remaining pods to finish..."
wait
echo "=== All pods completed! ==="
