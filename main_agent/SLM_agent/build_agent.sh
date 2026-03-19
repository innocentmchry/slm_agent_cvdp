#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Build script for iterative refinement agent

IMAGE_NAME="${1:-${IMAGE_NAME:-slm-agent-8001}}"

echo "Building iterative refinement agent Docker image: ${IMAGE_NAME}"
docker build -t "${IMAGE_NAME}" --no-cache .

if [ $? -eq 0 ]; then
    echo "✅ Build successful!"
    echo ""
    echo "Agent image: ${IMAGE_NAME}"
    echo ""
    echo "Fresh run:"
    echo "  python run_benchmark.py -f dataset.jsonl -l -g ${IMAGE_NAME} --force-agentic --force-agentic-include-harness -p target_repository"
    echo "Re run from failed:"
    echo "  python run_benchmark.py -f dataset.jsonl -l -g ${IMAGE_NAME} --force-agentic --force-agentic-include-harness -p existing_repository --start problem_id"
    echo "Evaluation only:"
    echo "  python run_benchmark.py -f dataset.jsonl -l -g ${IMAGE_NAME} --force-agentic --force-agentic-include-harness -p existing_repository --evaluate"
    echo ""
    echo "To configure the SLM model, set environment variables in .env: and build again"
else
    echo "❌ Build failed!"
    exit 1
fi
