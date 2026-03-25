#!/usr/bin/env python3
"""Unified API client for code generation - supports SLM, OpenAI, and Claude"""

import requests
import logging
import socket
from typing import Optional, Dict
from openai import OpenAI

logger = logging.getLogger(__name__)


def resolve_host_docker_internal(url: str) -> str:
    """
    Resolve host.docker.internal to actual host IP on Linux.
    
    On Mac/Windows, host.docker.internal works natively.
    On Linux, we need to find the host IP from the container's perspective.
    
    Args:
        url: Original URL that may contain host.docker.internal
        
    Returns:
        URL with host.docker.internal resolved to actual IP
    """
    if "host.docker.internal" not in url:
        return url
    
    try:
        # Try to resolve host.docker.internal (works on Mac/Windows)
        socket.gethostbyname("host.docker.internal")
        logger.info("host.docker.internal is natively supported")
        return url
    except socket.gaierror:
        # Not supported, we're likely on Linux
        logger.info("host.docker.internal not supported, attempting to find host IP...")
        
        try:
            # Method 1: Read default gateway from /proc/net/route
            # This is the Docker host IP from the container's perspective
            with open('/proc/net/route', 'r') as f:
                for line in f.readlines():
                    fields = line.strip().split()
                    if fields[1] == '00000000':  # Default gateway
                        # Gateway is in hex, little-endian format
                        gateway_hex = fields[2]
                        # Convert to IP address
                        ip_parts = [str(int(gateway_hex[i:i+2], 16)) 
                                   for i in range(6, -1, -2)]
                        host_ip = '.'.join(ip_parts)
                        
                        new_url = url.replace("host.docker.internal", host_ip)
                        logger.info(f"Resolved host.docker.internal to {host_ip}")
                        logger.info(f"Updated URL: {new_url}")
                        return new_url
        except Exception as e:
            logger.warning(f"Could not resolve host IP from /proc/net/route: {e}")
        
        # Method 2: Try using the default Docker bridge gateway (172.17.0.1)
        # This is the typical Docker host IP on Linux
        try:
            test_ip = "172.17.0.1"
            # Try to ping this IP (quick check)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((test_ip, 8001))
            sock.close()
            
            if result == 0:
                new_url = url.replace("host.docker.internal", test_ip)
                logger.info(f"Using default Docker bridge IP: {test_ip}")
                logger.info(f"Updated URL: {new_url}")
                return new_url
        except Exception as e:
            logger.warning(f"Could not test default Docker bridge IP: {e}")
        
        # If all fails, return original URL and log warning
        logger.warning("Could not resolve host.docker.internal - API calls may fail!")
        logger.warning("Consider using --add-host=host.docker.internal:host-gateway")
        return url


class UnifiedAPIClient:
    """Unified interface for SLM, OpenAI, and Claude APIs"""
    
    def __init__(self, api_type: str, model: str, max_length: int, timeout: int,
                 temperature: float = 0.15, top_p: float = 0.95,
                 api_url: Optional[str] = None, openai_api_key: Optional[str] = None,
                 claude_api_key: Optional[str] = None, claude_api_url: Optional[str] = None):
        """
        Initialize unified API client
        
        Args:
            api_type: Type of API ("slm", "openai", or "claude")
            model: Model name/identifier
            max_length: Maximum generation length
            timeout: Request timeout in seconds
            temperature: Sampling temperature
            top_p: Nucleus sampling parameter
            api_url: Base URL of SLM API (required for SLM)
            openai_api_key: OpenAI API key (required for OpenAI)
            claude_api_key: Claude API key (required for Claude)
            claude_api_url: Base URL of Claude API (optional, defaults to Anthropic API)
        """
        self.api_type = api_type.lower()
        self.model = model
        self.max_length = max_length
        self.timeout = timeout
        self.temperature = temperature
        self.top_p = top_p
        
        if self.api_type == "openai":
            if not openai_api_key:
                raise ValueError("OpenAI API key is required for OpenAI API type")
            self.openai_client = OpenAI(api_key=openai_api_key)
            logger.info(f"Initialized OpenAI API Client")
            logger.info(f"  Model: {model}")
            logger.info(f"  Max length: {max_length}")
            logger.info(f"  Temperature: {temperature}")
            logger.info(f"  Top-p: {top_p}")

        elif self.api_type == "claude":
            if not claude_api_key:
                raise ValueError("Claude API key is required for Claude API type")
            self.claude_api_key = claude_api_key
            self.claude_api_url = (claude_api_url or "https://api.anthropic.com").rstrip("/")
            logger.info("Initialized Claude API Client")
            logger.info(f"  URL: {self.claude_api_url}")
            logger.info(f"  Model: {model}")
            logger.info(f"  Max length: {max_length}")
            logger.info(f"  Temperature: {temperature}")
            logger.info(f"  Top-p: {top_p}")
            
        elif self.api_type == "slm":
            if not api_url:
                raise ValueError("API URL is required for SLM API type")
            # Resolve host.docker.internal on Linux
            self.api_url = resolve_host_docker_internal(api_url)
            logger.info(f"Initialized SLM API Client")
            logger.info(f"  URL: {self.api_url}")
            logger.info(f"  Model: {model}")
            logger.info(f"  Max length: {max_length}")
            logger.info(f"  Temperature: {temperature}")
            logger.info(f"  Top-p: {top_p}")
            
        else:
            raise ValueError(f"Unsupported API type: {api_type}. Must be 'slm', 'openai', or 'claude'")
    
    def generate(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None
    ) -> Optional[str]:
        """
        Generate code using the configured API
        
        Args:
            prompt: Input prompt with TASK, REQUIREMENTS, etc.
            temperature: Sampling temperature override
            top_p: Nucleus sampling override
            
        Returns:
            Generated text or None on failure
        """
        temperature = self.temperature if temperature is None else temperature
        top_p = self.top_p if top_p is None else top_p

        if self.api_type == "openai":
            return self._generate_openai(prompt, temperature, top_p)
        elif self.api_type == "claude":
            return self._generate_claude(prompt, temperature, top_p)
        elif self.api_type == "slm":
            return self._generate_slm(prompt, temperature, top_p)
        else:
            logger.error(f"Unknown API type: {self.api_type}")
            return None

    def _generate_claude(self, prompt: str, temperature: float, top_p: float) -> Optional[str]:
        """Generate using Claude (Anthropic Messages API)"""
        try:
            payload = {
                "model": self.model,
                "max_tokens": self.max_length,
                "temperature": temperature,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            }

            logger.info("Calling Claude API")
            logger.info(f"  Model: {self.model}, Temperature: {temperature}, Top-p: {top_p}")
            logger.info(f"  Prompt length: {len(prompt)} chars")

            response = requests.post(
                f"{self.claude_api_url}/v1/messages",
                headers={
                    "x-api-key": self.claude_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json=payload,
                timeout=self.timeout
            )

            if response.status_code == 200:
                data = response.json()
                content_blocks = data.get("content", [])
                text_blocks = [
                    block.get("text", "")
                    for block in content_blocks
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                result = "".join(text_blocks).strip()
                if result:
                    logger.info(f"Received {len(result)} characters from Claude")
                    return result

                logger.warning("Claude returned empty text content")
                return None

            logger.error(f"Claude API error {response.status_code}: {response.text}")
            return None

        except requests.Timeout:
            logger.error(f"Claude API timeout after {self.timeout}s")
            return None
        except requests.RequestException as e:
            logger.error(f"Claude API request failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error calling Claude API: {e}")
            return None
    
    def _generate_openai(self, prompt: str, temperature: float, top_p: float) -> Optional[str]:
        """Generate using OpenAI API"""
        try:
            logger.info(f"Calling OpenAI API")
            logger.info(f"  Model: {self.model}, Temperature: {temperature}, Top-p: {top_p}")
            logger.info(f"  Prompt length: {len(prompt)} chars")
            
            response = self.openai_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=self.max_length,
                temperature=temperature,
                top_p=top_p,
                timeout=self.timeout
            )
            
            if response.choices and len(response.choices) > 0:
                result = response.choices[0].message.content
                if result:
                    logger.info(f"Received {len(result)} characters from OpenAI")
                    return result
                else:
                    logger.warning("OpenAI returned empty response")
                    return None
            else:
                logger.error("OpenAI returned no choices")
                return None
                
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return None
    
    def _generate_slm(self, prompt: str, temperature: float, top_p: float) -> Optional[str]:
        """Generate using local SLM API"""
        try:
            payload = {
                "prompt": prompt,
                "max_length": self.max_length,
                "model": self.model,
                "temperature": temperature,
                "top_p": top_p
            }
            
            logger.info(f"Calling SLM API: {self.api_url}/generate")
            logger.info(f"  Model: {self.model}, Temperature: {temperature}, Top-p: {top_p}")
            logger.info(f"  Prompt length: {len(prompt)} chars")
            
            response = requests.post(
                f"{self.api_url}/generate",
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Try multiple field names that different SLM APIs might use
                for field in ['generated_text', 'text', 'response', 'output', 'result']:
                    if field in data:
                        result = data[field]
                        logger.info(f"Received {len(result)} bytes from SLM (field: {field})")
                        return result
                
                # Fallback: return whole response as string
                result = str(data)
                logger.warning(f"Unknown response format, returning as string: {len(result)} bytes")
                return result
            else:
                logger.error(f"SLM API error {response.status_code}: {response.text}")
                return None
                
        except requests.Timeout:
            logger.error(f"SLM API timeout after {self.timeout}s")
            return None
        except requests.RequestException as e:
            logger.error(f"SLM API request failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error calling SLM API: {e}")
            return None


# Backward compatibility alias
SLMAPIClient = UnifiedAPIClient
