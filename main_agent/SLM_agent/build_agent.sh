#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Build script for iterative refinement agent
#
# Usage: [API_TYPE=slm|openai|claude] [SLM_MODEL=<model>] ./build_agent.sh [image-name] [slm-port]
#
# Examples:
#   ./build_agent.sh                                                        # local model "phi" on port 8001
#   SLM_MODEL=granite4 ./build_agent.sh slm-agent-8002 8002                 # local model on port 8002
#   API_TYPE=openai SLM_MODEL=gpt-4o-mini ./build_agent.sh gpt-agent        # OpenAI
#   API_TYPE=claude SLM_MODEL=claude-sonnet-4-6 ./build_agent.sh claude-agent  # Claude
#
# Other optional overrides: SLM_MAX_LENGTH, SLM_TIMEOUT, SLM_TEMPERATURE, SLM_TOP_P
#
# The image is built on the benchmark simulation image (default nvidia/cvdp-sim:v1.0.0).
# Build that first from the benchmark root:
#   docker build -f docker/Dockerfile.sim -t nvidia/cvdp-sim:v1.0.0 .
# Set BASE_IMAGE to use a different one.
#
# API keys are not built into the image. Put OPENAI_USER_KEY / CLAUDE_API_KEY in the .env
# at the benchmark root; the harness passes them to the agent container.

cd "$(dirname "$0")"

SLM_PORT="${2:-${SLM_PORT:-8001}}"
IMAGE_NAME="${1:-${IMAGE_NAME:-slm-agent-${SLM_PORT}}}"

BUILD_ARGS=(--build-arg "SLM_PORT=${SLM_PORT}")
for var in BASE_IMAGE API_TYPE SLM_MODEL SLM_MAX_LENGTH SLM_TIMEOUT SLM_TEMPERATURE SLM_TOP_P; do
    [ -n "${!var}" ] && BUILD_ARGS+=(--build-arg "${var}=${!var}")
done

BASE="${BASE_IMAGE:-nvidia/cvdp-sim:v1.0.0}"
if ! docker image inspect "$BASE" >/dev/null 2>&1; then
    echo "❌ Base image $BASE not found. Build it first from the benchmark root:"
    echo "   docker build -f docker/Dockerfile.sim -t nvidia/cvdp-sim:v1.0.0 ."
    exit 1
fi

echo "Building iterative refinement agent Docker image: ${IMAGE_NAME}"
echo "API type: ${API_TYPE:-slm}, model: ${SLM_MODEL:-phi}, SLM port: ${SLM_PORT}"
docker build -t "${IMAGE_NAME}" --no-cache "${BUILD_ARGS[@]}" .

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
else
    echo "❌ Build failed!"
    exit 1
fi
