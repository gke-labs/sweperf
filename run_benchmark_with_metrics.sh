#!/bin/bash

DURATION=1200
CONCURRENCY=512

echo "Starting metrics collection in background..."
rm -f node_metrics.txt
(
  END_TIME=$((SECONDS + DURATION))
  while [ $SECONDS -lt $END_TIME ]; do
    kubectl top nodes --no-headers >> node_metrics.txt 2>/dev/null || true
    sleep 10
  done
) &
METRICS_PID=$!

echo "Starting submitter ($DURATION seconds, $CONCURRENCY pods)..."
./benchmark/submitter.sh benchmark/pod_template.yaml $CONCURRENCY $DURATION generated_images.txt

echo "Submitter finished. Stopping metrics collection..."
kill $METRICS_PID 2>/dev/null || true
wait $METRICS_PID 2>/dev/null || true

echo "Generating report..."
python3 process_metrics.py > report.md
cat report.md
