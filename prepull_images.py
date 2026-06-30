#!/usr/bin/env python3
import argparse
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../agent-sandbox/examples/agent-sandbox-rl')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../agent-sandbox/clients/python/agentic-sandbox-client')))

try:
    from agent_sandbox_rl import SandboxFleet
except ImportError as e:
    print(f"Failed to import agent_sandbox_rl: {e}")
    print("Make sure you have installed the k8s-agent-sandbox and agent-sandbox-rl packages.")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Prepull images to GKE cluster using agent-sandbox-rl")
    parser.add_argument("images", nargs="+", help="List of images to prepull")
    args = parser.parse_args()

    # Uses the ambient kubeconfig
    fleet = SandboxFleet()
    
    tasks = [{"id": f"task-{i}", "image": img} for i, img in enumerate(args.images)]
    fleet.load_tasks(tasks)
    fleet.plan()
    
    print(f"Pre-pulling images: {args.images}")
    fleet.prepull(wait=True)
    print("Pre-pull complete.")

if __name__ == "__main__":
    main()
