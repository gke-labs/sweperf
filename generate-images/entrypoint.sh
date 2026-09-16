#!/bin/bash
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -e

/usr/bin/python3 -c "import sys; sys.path.append('/'); import replay; replay.wait_for_signals()"

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

echo "Running environment setup..."
mkdir -p /testbed
chown swe-bench:swe-bench /testbed

# Patch the setup script to forcefully reset any files dirtied by pip install -e .
sed -i 's/git checkout /git reset --hard \&\& git clean -fd \&\& git checkout /g' /setups/setup_${INSTANCE_ID}.sh

if su swe-bench -c "export PIP_INDEX_URL='$PIP_INDEX_URL'; bash /setups/setup_${INSTANCE_ID}.sh"; then
    echo "Setup successful. Running evaluation replay as swe-bench user..."
    su swe-bench -c "/usr/bin/python3 /replay.py /traces/${INSTANCE_ID}_trace.json" || {
        echo 'Task failed during replay, sleeping for debug'
        sleep 3600
    }
else
    echo 'Task failed during setup, sleeping for debug'
    sleep 3600
fi
