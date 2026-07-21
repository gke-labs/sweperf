#!/bin/bash
set -e

if [ "$#" -lt 4 ] || [ "$#" -gt 5 ]; then
    echo "Usage: $0 <pod_template.yaml> <concurrency> <duration_seconds> <images_file> [DO_GIT_PULL]"
    exit 1
fi

TEMPLATE=$1
CONCURRENCY=$2
DURATION=$3
INSTANCES_FILE=$4
DO_GIT_PULL=${5:-false}

if [ ! -f "$TEMPLATE" ]; then
    echo "Error: Template file $TEMPLATE not found."
    exit 1
fi

if [ ! -f "$INSTANCES_FILE" ]; then
    echo "Error: Instances file $INSTANCES_FILE not found."
    exit 1
fi

mapfile -t INSTANCES < <(grep -v '^$' "$INSTANCES_FILE")
NUM_INSTANCES=${#INSTANCES[@]}

if [ "$NUM_INSTANCES" -eq 0 ]; then
    echo "Error: No instances found in $INSTANCES_FILE."
    exit 1
fi

echo "=== SWE-bench Custom Submitter ==="
echo "Concurrency: $CONCURRENCY"
echo "Duration: $DURATION seconds"
echo "Unique Instances: $NUM_INSTANCES"
echo "----------------------------------"

# Main event loop
START_TIME=$(date +%s)
END_TIME=$(( START_TIME + DURATION ))
idx=1

# Maintain concurrency by continuously polling the Kubernetes API
# until the DURATION window ends.
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
            
            # Select a random SWE-bench instance for this pod
            rand_idx=$(( RANDOM % NUM_INSTANCES ))
            instance="${INSTANCES[$rand_idx]}"
            UNIVERSAL_IMAGE="${UNIVERSAL_IMAGE:-sweperf:universal}"
            pod_name="${POD_PREFIX}${idx}-$RANDOM"
            
            sed -e "s|{{IMAGE}}|$UNIVERSAL_IMAGE|g" -e "s|{{INSTANCE_ID}}|$instance|g" -e "s|{{NAME}}|$pod_name|g" -e "s|{{DO_GIT_PULL}}|$DO_GIT_PULL|g" "$TEMPLATE" >> "$batch_yaml"
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
