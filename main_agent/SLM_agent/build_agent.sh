#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Build script for iterative refinement agent

echo "Building iterative refinement agent Docker image..."
docker build -t slm-agent-8001 --no-cache .

if [ $? -eq 0 ]; then
    echo "✅ Build successful!"
    echo ""
    echo "Agent image: slm-agent-8001"
    echo ""
    echo "Fresh run:"
    echo "  python run_benchmark.py -f dataset.jsonl -l -g slm-agent-8001 --force-agentic --force-agentic-include-harness -p target_repository"
    echo "Re run from failed:"
    echo "  python run_benchmark.py -f dataset.jsonl -l -g slm-agent-8001 --force-agentic --force-agentic-include-harness -p existing_repository --start problem_id"
    echo "Evaluation only:"
    echo "  python run_benchmark.py -f dataset.jsonl -l -g slm-agent-8001 --force-agentic --force-agentic-include-harness -p existing_repository --evaluate"
    echo ""
    echo "To configure the SLM model, set environment variables in .env: and build again"
    echo "  SLM_API_URL=http://localhost:8001"
else
    echo "❌ Build failed!"
    exit 1
fi
