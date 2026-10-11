# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import os
import logging
import requests
from typing import Optional
from src.config_manager import config
from src.model_helpers import ModelHelpers

logging.basicConfig(level=logging.INFO)


class Claude_Instance:
    """Anthropic Claude model implementation compatible with benchmark model interface."""

    def __init__(self, context: str = "You are a helpful assistant.", key=None, model=None):
        if model is None:
            model = "claude-sonnet-4-6"

        self.context = context
        self.model = model
        self.debug = False

        self.api_key = key or config.get("CLAUDE_API_KEY") or config.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("Unable to create Claude Model - set CLAUDE_API_KEY or ANTHROPIC_API_KEY in .env")

        self.api_url = (config.get("CLAUDE_API_URL") or "https://api.anthropic.com").rstrip("/")
        logging.info(f"Created Claude Model using provided key. Using model: {self.model}")

    @property
    def requires_evaluation(self) -> bool:
        return True

    def set_debug(self, debug: bool = True) -> None:
        self.debug = debug
        logging.info(f"Debug mode {'enabled' if debug else 'disabled'}")

    def prompt(self, prompt, schema: str = None, prompt_log: str = "", files: Optional[list] = None, timeout: int = 60, category: Optional[int] = None):
        helper = ModelHelpers()
        system_prompt = helper.create_system_prompt(self.context, schema, category)

        if timeout == 60:
            timeout = config.get("MODEL_TIMEOUT", 60)

        expected_single_file = files and len(files) == 1 and schema is None

        if prompt_log:
            try:
                os.makedirs(os.path.dirname(prompt_log), exist_ok=True)
                temp_log = f"{prompt_log}.tmp"
                with open(temp_log, "w+") as f:
                    f.write(system_prompt + "\n\n----------------------------------------\n" + prompt)
                os.replace(temp_log, prompt_log)
            except Exception as e:
                logging.error(f"Failed to write prompt log to {prompt_log}: {str(e)}")
                raise

        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
            "system": system_prompt,
        }

        if self.debug:
            logging.debug(f"Requesting prompt using model: {self.model}")
            logging.debug(f"Prompt length: {len(prompt)}")

        try:
            response = requests.post(
                f"{self.api_url}/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()

            content_blocks = data.get("content", [])
            text_blocks = [
                block.get("text", "")
                for block in content_blocks
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            content = "".join(text_blocks).strip()

            if not content:
                raise ValueError("Claude returned empty response")

            if schema is not None and content.startswith('{') and content.endswith('}'):
                content = helper.fix_json_formatting(content)

            return helper.parse_model_response(content, files, expected_single_file)

        except requests.Timeout:
            raise ValueError(f"Unable to get response from Claude model: timeout after {timeout}s")
        except requests.RequestException as e:
            raise ValueError(f"Unable to get response from Claude model: {str(e)}")
        except Exception as e:
            raise ValueError(f"Unable to get response from Claude model: {str(e)}")
