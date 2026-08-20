#!/bin/bash
# Runs a single sweperf case natively via docker (for use inside the nested VM)
INSTANCE_ID=$1
if [ -z "$INSTANCE_ID" ]; then
    echo "Usage: $0 <instance_id>"
    exit 1
fi
docker run -d --rm --name "sweperf-$INSTANCE_ID" -e INSTANCE_ID="$INSTANCE_ID" sweperf:universal
