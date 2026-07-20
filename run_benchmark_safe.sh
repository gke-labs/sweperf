#!/bin/bash
export KUBECONFIG=$(pwd)/kubeconfig_isolated.yaml
echo "Setting up isolated kubeconfig..."
gcloud container clusters get-credentials sweperf-bench-2 --zone=us-central1-b --project=bsalmon-gke-dev
echo "Deleting old swebench pods..."
kubectl delete pods -l app=swebench
echo "Launching benchmark..."
./sweperf run-benchmark 7200 800
