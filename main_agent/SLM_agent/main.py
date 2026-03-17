#!/usr/bin/env python3
"""Main entry point for SLM Agent - Supports both SLM and OpenAI GPT-4o-mini"""

import sys
import os
from core.agent import IterativeRefinementAgent
from config.settings import AgentConfig


def main():
    """Main entry point"""
    print("=" * 60)
    print("SLM Agent Starting...")
    
    # Show current configuration
    api_type = os.getenv("API_TYPE", "slm")
    model = os.getenv("SLM_MODEL", "granite")
    print(f"API Type: {api_type}")
    print(f"Model: {model}")
    
    if api_type == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            print("❌ ERROR: OPENAI_API_KEY environment variable is required for OpenAI API type")
            print("   Please set it with: export OPENAI_API_KEY=your_api_key_here")
            return 1
        print("✅ OpenAI API key configured")
    else:
        api_url = os.getenv("SLM_API_URL", "http://host.docker.internal:8001")
        print(f"SLM API URL: {api_url}")
    
    print("=" * 60)
    
    # Custom configuration
    # Config class get os.getenv variables if set
    config = AgentConfig(
        max_iterations=3,
        # slm_model will be read from ENV variable
        enable_port_validation=False,
        use_few_shot_examples=False
    )

    # Create and run agent
    agent = IterativeRefinementAgent(config)
    exit_code = agent.run()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())