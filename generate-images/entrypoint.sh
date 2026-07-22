#!/bin/bash
set -e

if [ "${USE_GCP_CACHE}" == "1" ]; then
    echo "USE_GCP_CACHE=1 detected. Fetching metadata token..."
    TOKEN=$(curl -sSf --connect-timeout 2 -H "Metadata-Flavor: Google" http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])" || echo "")
    if [ -n "$TOKEN" ]; then
        if [ -n "$PIP_INDEX_URL_TEMPLATE" ]; then
            export PIP_INDEX_URL="${PIP_INDEX_URL_TEMPLATE/\{TOKEN\}/$TOKEN}"
            echo "Successfully configured PIP_INDEX_URL for Artifact Registry caching."
        else
            echo "Warning: PIP_INDEX_URL_TEMPLATE not set in pod spec."
        fi

    else
        echo "Warning: Failed to fetch GCP token from metadata server. Falling back to public PyPI."
    fi
fi

python3 -c "import sys; sys.path.append('/'); import replay; replay.wait_for_signals()"

echo "Running environment setup..."
mkdir -p /testbed
chown swe-bench:swe-bench /testbed
if su swe-bench -c "export PIP_INDEX_URL='$PIP_INDEX_URL'; bash /setups/setup_${INSTANCE_ID}.sh"; then
    echo "Setup successful. Running evaluation replay as swe-bench user..."
    su swe-bench -c "python3 /replay.py /traces/${INSTANCE_ID}_trace.json" || {
        echo 'Task failed during replay, sleeping for debug'
        sleep 3600
    }
else
    echo 'Task failed during setup, sleeping for debug'
    sleep 3600
fi
