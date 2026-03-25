# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import os
import logging
import requests
from typing import Optional, Dict, Any
from src.config_manager import config
from src.model_helpers import ModelHelpers

logging.basicConfig(level=logging.INFO)


class LocalServer_Instance:
    """Local LLM server implementation compatible with benchmark model interface."""

    def __init__(self, context: str = "You are a helpful assistant.", key=None, model=None):
        if model is None:
            model = "local_server"

        self.context = context
        self.model = model
        self.debug = False

        self.api_url = (config.get("LOCAL_SERVER_URL") or "http://127.0.0.1:8001").rstrip("/")
        self.api_key = key or config.get("LOCAL_SERVER_API_KEY")
        self.api_style = (config.get("LOCAL_SERVER_API_STYLE") or "auto").strip().lower()
        self.server_model = config.get("LOCAL_SERVER_MODEL")

        if self.api_style not in {"auto", "openai", "claude", "slm"}:
            raise ValueError(
                "Invalid LOCAL_SERVER_API_STYLE. Use one of: auto, openai, claude, slm"
            )

        logging.info(
            f"Created LocalServer model. model={self.model}, url={self.api_url}, style={self.api_style}"
        )

    @property
    def requires_evaluation(self) -> bool:
        return True

    def set_debug(self, debug: bool = True) -> None:
        self.debug = debug
        logging.info(f"Debug mode {'enabled' if debug else 'disabled'}")

    def _write_prompt_log(self, prompt_log: str, system_prompt: str, prompt: str) -> None:
        if not prompt_log:
            return

        os.makedirs(os.path.dirname(prompt_log), exist_ok=True)
        temp_log = f"{prompt_log}.tmp"
        with open(temp_log, "w+") as f:
            f.write(system_prompt + "\n\n----------------------------------------\n" + prompt)
        os.replace(temp_log, prompt_log)

    def _extract_openai_content(self, data: Dict[str, Any]) -> str:
        choices = data.get("choices", [])
        if not choices:
            return ""

        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text") or part.get("content")
                    if isinstance(text, str):
                        text_parts.append(text)
            return "".join(text_parts).strip()

        return ""

    def _extract_claude_content(self, data: Dict[str, Any]) -> str:
        content_blocks = data.get("content", [])
        text_blocks = [
            block.get("text", "")
            for block in content_blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "".join(text_blocks).strip()

    def _extract_slm_content(self, data: Dict[str, Any]) -> str:
        content = data.get("response", "")
        if isinstance(content, str):
            return content.strip()
        return ""

    def _build_model_name(self) -> Optional[str]:
        """Select model name to send to local server.

        For SLM /generate servers, sending the benchmark alias (e.g. local_server)
        can be rejected. By default, omit model unless LOCAL_SERVER_MODEL is set.
        """
        if self.server_model and str(self.server_model).strip():
            return str(self.server_model).strip()
        return None

    def _post_openai(self, prompt: str, system_prompt: str, timeout: int) -> str:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        }
        model_name = self._build_model_name() or self.model
        if model_name:
            payload["model"] = model_name

        response = requests.post(
            f"{self.api_url}/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return self._extract_openai_content(response.json())

    def _post_claude(self, prompt: str, system_prompt: str, timeout: int) -> str:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        payload = {
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
            "system": system_prompt,
        }
        model_name = self._build_model_name() or self.model
        if model_name:
            payload["model"] = model_name

        response = requests.post(
            f"{self.api_url}/v1/messages",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return self._extract_claude_content(response.json())

    def _post_slm(self, prompt: str, timeout: int) -> str:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: Dict[str, Any] = {
            "prompt": prompt,
            "max_tokens": 4096,
            "temperature": 0.7,
            "top_p": 0.9,
        }
        model_name = self._build_model_name()
        if model_name:
            payload["model"] = model_name

        response = requests.post(
            f"{self.api_url}/generate",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return self._extract_slm_content(response.json())

    def prompt(self, prompt, schema: str = None, prompt_log: str = "", files: Optional[list] = None, timeout: int = 60, category: Optional[int] = None):
        helper = ModelHelpers()
        system_prompt = helper.create_system_prompt(self.context, schema, category)

        if timeout == 60:
            timeout = config.get("MODEL_TIMEOUT", 60)

        expected_single_file = files and len(files) == 1 and schema is None

        try:
            self._write_prompt_log(prompt_log, system_prompt, prompt)
        except Exception as e:
            logging.error(f"Failed to write prompt log to {prompt_log}: {str(e)}")
            raise

        if self.debug:
            logging.debug(f"Requesting prompt using local server model: {self.model}")
            logging.debug(f"Local server URL: {self.api_url}")
            logging.debug(f"API style: {self.api_style}")

        try:
            content = ""
            if self.api_style == "openai":
                content = self._post_openai(prompt, system_prompt, timeout)
            elif self.api_style == "claude":
                content = self._post_claude(prompt, system_prompt, timeout)
            elif self.api_style == "slm":
                content = self._post_slm(prompt, timeout)
            else:
                openai_error = None
                claude_error = None
                try:
                    content = self._post_openai(prompt, system_prompt, timeout)
                except requests.RequestException as e:
                    openai_error = e
                    try:
                        content = self._post_claude(prompt, system_prompt, timeout)
                        if self.debug:
                            logging.debug(f"OpenAI-style endpoint failed, Claude-style succeeded: {str(openai_error)}")
                    except requests.RequestException as e2:
                        claude_error = e2
                        content = self._post_slm(prompt, timeout)
                        if self.debug:
                            logging.debug(
                                "OpenAI-style and Claude-style endpoints failed, SLM-style succeeded: "
                                f"openai={str(openai_error)}, claude={str(claude_error)}"
                            )

            if not content:
                raise ValueError("Local server returned empty response")

            if schema is not None and content.startswith('{') and content.endswith('}'):
                content = helper.fix_json_formatting(content)

            return helper.parse_model_response(content, files, expected_single_file)

        except requests.Timeout:
            raise ValueError(f"Unable to get response from local server model: timeout after {timeout}s")
        except requests.RequestException as e:
            raise ValueError(f"Unable to get response from local server model: {str(e)}")
        except Exception as e:
            raise ValueError(f"Unable to get response from local server model: {str(e)}")