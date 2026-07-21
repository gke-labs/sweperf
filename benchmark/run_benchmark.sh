#!/bin/bash
set -e

if [ "$#" -lt 4 ]; then
    echo "Usage: $0 <mode: universal|legacy> <pod_template.yaml> <concurrency> <duration_seconds> <target_file> [extra_args...]"
    echo "Example: $0 universal benchmark/pod_template_universal.yaml 50 3600 instances_target.txt"
    exit 1
fi

MODE=$1
TEMPLATE=$2
CONCURRENCY=$3
DURATION=$4
TARGET_FILE=$5
shift 5

# Clean old telemetry to prevent metric skew
echo "Cleaning old telemetry files..."
rm -f concurrency.txt node_metrics.txt pods.json benchmark_report.md

echo "=============================================="
echo " Starting Telemetry Daemons in Background"
echo " Duration mapped to: $DURATION seconds"
echo "=============================================="

# Launch background watchers
python3 benchmark/collector.py "$DURATION" &
COLLECTOR_PID=$!

python3 benchmark/node_watcher.py "$DURATION" &
WATCHER_PID=$!

echo "=============================================="
echo " Firing Submitter ($MODE mode)"
echo "=============================================="

if [ "$MODE" == "universal" ]; then
    bash benchmark/submitter_universal.sh "$TEMPLATE" "$CONCURRENCY" "$DURATION" "$TARGET_FILE" "$@"
elif [ "$MODE" == "legacy" ]; then
    bash benchmark/submitter.sh "$TEMPLATE" "$CONCURRENCY" "$DURATION" "$TARGET_FILE" "$@"
else
    echo "Error: Mode must be strictly 'universal' or 'legacy'"
    kill $COLLECTOR_PID $WATCHER_PID
    exit 1
fi

echo "=============================================="
echo " Submitter complete! Awaiting final telemetry logs..."
echo "=============================================="
wait $COLLECTOR_PID
wait $WATCHER_PID

echo "Generating markdown report..."
python3 benchmark/process_metrics.py > benchmark_report.md

echo "All complete! Wrote artifact summary to benchmark_report.md"
