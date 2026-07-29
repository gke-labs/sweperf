#!/bin/bash
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
sed -i 's/.*apt-get.*/true/g' /setups/setup_${INSTANCE_ID}.sh
sed -i 's/.*locale.gen.*/true/g' /setups/setup_${INSTANCE_ID}.sh
sed -i '/conda activate/a rm -rf $CONDA_PREFIX/compiler_compat/ld 2>/dev/null || rm -rf /home/swe-bench/miniconda3/envs/*/compiler_compat/ld 2>/dev/null || true' /setups/setup_${INSTANCE_ID}.sh
sed -i 's/python3 -m pip install --upgrade pip setuptools wheel/python3 -m pip install --upgrade pip "setuptools<69.0.0" wheel/g' /setups/setup_${INSTANCE_ID}.sh
sed -i 's/python3 -m pip install -e \/testbed/python3 -m pip install --no-build-isolation -e \/testbed/g' /setups/setup_${INSTANCE_ID}.sh
sed -i '/pip install --no-build-isolation -e \/testbed/i python3 -m pip install flit_core pybind11 setuptools_scm extension_helpers' /setups/setup_${INSTANCE_ID}.sh

if su swe-bench -c "export PIP_INDEX_URL='$PIP_INDEX_URL'; bash /setups/setup_${INSTANCE_ID}.sh"; then
    echo "Setup successful. Running evaluation replay as swe-bench user..."
    su swe-bench -c "/usr/bin/python3 /replay.py /traces/${INSTANCE_ID}_trace.json" || {
        if [ "${SLEEP_ON_FAILURE}" == "1" ] || [ "${SLEEP_ON_FAILURE}" == "true" ]; then
            echo 'Task failed during replay, sleeping for debug'
            sleep 3600
        else
            echo 'Task failed during replay'
            exit 1
        fi
    }
else
    if [ "${SLEEP_ON_FAILURE}" == "1" ] || [ "${SLEEP_ON_FAILURE}" == "true" ]; then
        echo 'Task failed during setup, sleeping for debug'
        sleep 3600
    else
        echo 'Task failed during setup'
        exit 1
    fi
fi
