#!/bin/bash
set -e

if [ "$#" -ne 4 ]; then
    echo "Usage: $0 <pod_template.yaml> <concurrency> <duration_seconds> <images_file>"
    exit 1
fi

TEMPLATE=$1
CONCURRENCY=$2
DURATION=$3
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
echo "Duration: $DURATION seconds"
echo "Unique Images: $NUM_IMAGES"
echo "----------------------------------"

# Main event loop
START_TIME=$(date +%s)
END_TIME=$(( START_TIME + DURATION ))
idx=1

# We rely on a consistent prefix to find our active pods
POD_PREFIX="swebench-run-"

while [ $(date +%s) -lt $END_TIME ]; do
    # Count active pods using label selector
    active_pods=$(kubectl get pods -l app=swebench --field-selector=status.phase!=Succeeded,status.phase!=Failed --no-headers 2>/dev/null | wc -l || echo 0)

    if [ "$active_pods" -lt "$CONCURRENCY" ]; then
        to_launch=$(( CONCURRENCY - active_pods ))
        echo "Active pods: $active_pods. Launching $to_launch new pods..."
        
        batch_yaml=$(mktemp)
        count=0
        
        for (( i=0; i<to_launch; i++ )); do
            if [ $(date +%s) -ge $END_TIME ]; then
                break 2
            fi
            
            rand_idx=$(( RANDOM % NUM_IMAGES ))
            image="${IMAGES[$rand_idx]}"
            pod_name="${POD_PREFIX}${idx}-$RANDOM"
            
            sed -e "s|{{IMAGE}}|$image|g" -e "s|{{NAME}}|$pod_name|g" "$TEMPLATE" >> "$batch_yaml"
            echo "---" >> "$batch_yaml"
            
            count=$((count + 1))
            idx=$((idx + 1))
            
            # Submit in batches of 50 or when the loop is done
            if [ "$count" -ge 50 ] || [ "$i" -eq $((to_launch - 1)) ]; then
                echo "Submitting batch of $count pods..."
                # Run the kubernetes apply command in background natively avoiding network blocks
                kubectl apply -f "$batch_yaml" > /dev/null 2>&1 &
                
                # Re-initialize the next batch
                batch_yaml=$(mktemp)
                count=0
            fi
        done
        # Ensure all background batch submissions cleanly finish before looping
        wait
        rm -f "$batch_yaml"
    fi
    
    # Sleep gently before checking the cluster state again
    sleep 10
done

echo "Time is up! Let's just wait a bit to let Kubernetes settle..."
sleep 10
echo "=== Submitter completed! ==="
