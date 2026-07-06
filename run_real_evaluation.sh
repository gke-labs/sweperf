#!/bin/bash
set -e

# 1. Ensure the Gemini API key is set
if [ -z "$GEMINI_API_KEY" ]; then
    if [ -f "gemini.key" ]; then
        export GEMINI_API_KEY=$(cat gemini.key | tr -d '\n')
    else
        echo "Error: GEMINI_API_KEY is required and gemini.key file is missing."
        exit 1
    fi
fi

if [ -z "$GEMINI_API_KEY" ]; then
    echo "Error: GEMINI_API_KEY is required to run the real agent evaluation."
    exit 1
fi

echo "Setting up virtual environment and installing dependencies..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate

# 2. Install required packages
pip install --index-url https://pypi.org/simple google-generativeai kubernetes
pip install --index-url https://pypi.org/simple -e '/usr/local/google/home/bsalmon/git/agent-sandbox/examples/agent-sandbox-rl[swebench]'

# Clone and install R2E-Gym if not present
if [ ! -d "/usr/local/google/home/bsalmon/git/R2E-Gym" ]; then
    echo "Cloning R2E-Gym..."
    git clone https://github.com/R2E-Gym/R2E-Gym.git /usr/local/google/home/bsalmon/git/R2E-Gym
fi
pip install --index-url https://pypi.org/simple -e /usr/local/google/home/bsalmon/git/R2E-Gym

# 3. Configure run limits (can be overridden by environment variables)
export TASKS_LIMIT=${TASKS_LIMIT:-1}
export MAX_CONCURRENT=${MAX_CONCURRENT:-1}

echo ""
echo "=================================================="
echo "Starting Real SWE-bench Evaluation with Gemini Agent"
echo "Tasks Limit: $TASKS_LIMIT"
echo "Concurrency: $MAX_CONCURRENT"
echo "=================================================="

# 4. Run the benchmark
python fleet_benchmark.py
