# Base image: the same simulation image the benchmark harness uses (OSS_SIM_IMAGE), so the
# agent's own test runs see the same cocotb, pytest, Icarus and Verilator as the evaluation.
# Build it first from the benchmark root:
#   docker build -f docker/Dockerfile.sim -t nvidia/cvdp-sim:v1.0.0 .
ARG BASE_IMAGE=nvidia/cvdp-sim:v1.0.0
FROM ${BASE_IMAGE}

WORKDIR /app

# Keep packages that harnesses install at run time on the versions already in the image
RUN pip freeze | grep '==' > /etc/pip-constraints.txt
ENV PIP_CONSTRAINT=/etc/pip-constraints.txt

# Agent dependencies
RUN pip install --no-cache-dir requests python-dotenv pyyaml openai

# Create /code directory for mounted volumes
RUN mkdir -p /code && chmod 777 /code
RUN mkdir -p /app/config
RUN mkdir -p /app/core
RUN mkdir -p /app/hdl
RUN mkdir -p /app/llm
RUN mkdir -p /app/prompts
RUN mkdir -p /app/testing
RUN mkdir -p /app/utils


# Copy dirs
COPY config/ /app/config/
COPY core/ /app/core/
COPY hdl/ /app/hdl/
COPY llm/ /app/llm/
COPY prompts/ /app/prompts/
COPY testing/ /app/testing/
COPY utils/ /app/utils/

# Copy the agent code
COPY __init__.py /app/__init__.py
COPY main.py /app/main.py

# Make it executable
RUN chmod +x /app/main.py


# Set Python path to find modules
ENV PYTHONPATH=/app

# Model configuration, chosen at build time with --build-arg (see build_agent.sh).
# Supported API types: slm, openai, claude
ARG API_TYPE=slm
# Model name sent to the API or local server, e.g. phi, granite4, deepseek, smollm, jamba,
# phi4-reasoning, phi4-custom, nemotron, gpt-4o-mini, claude-sonnet-4-6
ARG SLM_MODEL=phi
# Port of the local model server on the host (slm mode only)
ARG SLM_PORT=8001
ARG SLM_MAX_LENGTH=32768
ARG SLM_TIMEOUT=1800
ARG SLM_TEMPERATURE=0.7
ARG SLM_TOP_P=0.95

ENV API_TYPE=${API_TYPE}
ENV SLM_MODEL=${SLM_MODEL}
ENV SLM_API_URL=http://host.docker.internal:${SLM_PORT}
ENV SLM_MAX_LENGTH=${SLM_MAX_LENGTH}
ENV SLM_TIMEOUT=${SLM_TIMEOUT}
ENV SLM_TEMPERATURE=${SLM_TEMPERATURE}
ENV SLM_TOP_P=${SLM_TOP_P}

# API keys are NOT stored in the image. The benchmark harness passes OPENAI_USER_KEY and
# CLAUDE_API_KEY from the repo root .env into the container at run time.

# Set the entrypoint
ENTRYPOINT ["python3", "/app/main.py"]
