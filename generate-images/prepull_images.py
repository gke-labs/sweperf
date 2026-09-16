#!/usr/bin/env python3
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
    parser.add_argument("images", nargs="*", help="List of images to prepull")
    parser.add_argument("--image-file", type=str, help="Path to a text file containing image tags to prepull, one per line")
    args = parser.parse_args()

    if args.image_file and os.path.exists(args.image_file):
        with open(args.image_file, "r") as f:
            file_images = [line.strip() for line in f if line.strip()]
            args.images.extend(file_images)
            
    if not args.images:
        print("Error: No images provided to prepull.")
        sys.exit(1)

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
