# Use the open-source verification base image which includes Verilator, Icarus, etc.
FROM ghcr.io/hdl/sim/osvb

WORKDIR /app

# Install Python dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3-pip \
        python3-requests \
    && rm -rf /var/lib/apt/lists/*

# Install requests library for API calls
RUN pip3 install --no-cache-dir requests
#RUN pip3 install --no-cache-dir cocotb==1.9.2
RUN pip3 install --no-cache-dir python-dotenv
RUN pip install pyyaml
RUN pip3 install --no-cache-dir openai

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

# Set environment variables for model
# Supported API types: slm, openai, claude
# ENV API_TYPE=openai
# ENV API_TYPE=claude
ENV API_TYPE=slm 
# ENV OPENAI_API_KEY="your_key_here"
# ENV CLAUDE_API_URL="https://api.anthropic.com"
# ENV CLAUDE_API_KEY="key"
# ENV SLM_MODEL=gpt-4o-mini
# ENV SLM_MODEL=claude-sonnet-4-6
#ENV SLM_MODEL=granite4
ENV SLM_MODEL=smollm
# ENV SLM_MODEL=phi
# ENV SLM_MAX_LENGTH=16384
# ENV SLM_MAX_LENGTH=16384
ENV SLM_MAX_LENGTH=12288
ENV SLM_TIMEOUT=300
ENV SLM_TEMPERATURE=0.7
# ENV SLM_TOP_P=0.9

# Set the entrypoint
ENTRYPOINT ["python3", "/app/main.py"]
