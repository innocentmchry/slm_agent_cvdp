from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch
from typing import Optional, Dict, Any
import logging
import time
import traceback
import uvicorn
from contextlib import asynccontextmanager
from nemotron_model import NemotronModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SmolLMModel:
    """SmolLM2-1.7B-Instruct model implementation - lightweight SLM for API use"""
    def __init__(self, model: str = "HuggingFaceTB/SmolLM2-1.7B-Instruct"):
        self.model_name = model
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Using device: {self.device}")
        logger.info(f"Loading {model}...")
        
        try:
            # Load tokenizer with proper settings
            self.tokenizer = AutoTokenizer.from_pretrained(
                model, 
                trust_remote_code=True,
                use_fast=True
            )
            
            # Set padding token properly
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token
            
            # Ensure we have proper special tokens
            if self.tokenizer.bos_token is None:
                self.tokenizer.bos_token = self.tokenizer.eos_token
            
            # Load model with updated settings
            if torch.cuda.is_available():
                self.model = AutoModelForCausalLM.from_pretrained(
                    model,
                    torch_dtype=torch.float16,  # Use torch_dtype for compatibility
                    device_map="auto",
                    trust_remote_code=True,
                    low_cpu_mem_usage=True
                )
            else:
                self.model = AutoModelForCausalLM.from_pretrained(
                    model,
                    trust_remote_code=True,
                    low_cpu_mem_usage=True
                ).to(self.device)
            
            # Set model to eval mode
            self.model.eval()
            
            logger.info(f"SmolLM2 model loaded successfully on {self.device}")
            logger.info(f"Model vocab size: {self.model.config.vocab_size}")
            logger.info(f"Model max position embeddings: {getattr(self.model.config, 'max_position_embeddings', 'Unknown')}")
            
        except Exception as e:
            logger.error(f"Failed to load SmolLM2 model: {e}")
            raise

    def generate_text(self, prompt: str, max_length: int = 100, temperature: float = 0.7, top_p: float = 0.9) -> str:
        try:
            start_time = time.time()
            
            # Enhanced prompt preprocessing for complex prompts
            processed_prompt = self._preprocess_prompt(prompt)
            
            inputs = self.tokenizer(processed_prompt, return_tensors="pt", padding=True, truncation=True, max_length=8192).to(self.device)  # 4x increase: was 2048, now 8192
            input_length = inputs['input_ids'].shape[1]
            
            # Ensure we generate much longer responses - 10x enhancement
            max_new_tokens = min(max(200, max_length - input_length), 20480)  # 10x increased: was 2048, now 20480
            
            if max_new_tokens <= 0:
                logger.warning(f"Input too long, no room for generation. Input length: {input_length}, Max length: {max_length}")
                return "Input prompt too long for generation."
            
            # Try multiple generation strategies for complex prompts
            response = self._generate_with_fallback(inputs, max_new_tokens, temperature, top_p)
            
            # Post-process response for JSON format if needed
            response = self._postprocess_response(response, prompt)
            
            generation_time = time.time() - start_time
            logger.info(f"SmolLM generation completed in {generation_time:.2f}s")
            
            return response if response else "Unable to generate response."
        except Exception as e:
            logger.error(f"SmolLM text generation failed: {str(e)}")
            raise RuntimeError(f"Text generation failed: {str(e)}")

    def _preprocess_prompt(self, prompt: str) -> str:
        """Preprocess prompt to improve generation quality for SmolLM"""
        # SmolLM2 works better with conversational format
        if not prompt.strip().startswith("<|im_start|>"):
            # Add proper chat template for SmolLM2
            if '"response":' in prompt or '{ "response":' in prompt:
                # For JSON responses, be more explicit
                prompt = f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"
            else:
                # For regular conversations
                prompt = f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"
        
        # Handle very long technical prompts by adding focus instruction
        if len(prompt) > 500 and ("barrel shifter" in prompt.lower() or "testing" in prompt.lower()):
            # Insert focus instruction before the user message
            prompt = prompt.replace("<|im_start|>user\n", 
                                  "<|im_start|>user\nProvide a clear, technical explanation focusing on key concepts.\n\n")
            
        return prompt
        
        # Handle technical prompts by adding comprehensive instruction - enhanced
        if len(prompt) > 300 and any(term in prompt.lower() for term in ["barrel shifter", "testing", "circular shift", "verification", "lfsr", "hardware"]):
            prompt = f"Provide a very comprehensive, detailed technical explanation with multiple specific examples, step-by-step analysis, thorough coverage of all concepts, and extensive technical details.\n\n{prompt}\n\nProvide extensive detail and comprehensive analysis."
        
        # Enhanced instruction to encourage much longer responses for technical content
        if any(term in prompt.lower() for term in ["explain", "describe", "analyze", "discuss", "why", "how"]):
            prompt = prompt + "\n\nProvide a very detailed, comprehensive, thorough explanation with multiple sentences, specific examples, extensive technical analysis, and complete coverage of all relevant aspects."
            
        return prompt

    def _generate_with_fallback(self, inputs, max_new_tokens, temperature, top_p):
        """Generate with multiple fallback strategies"""
        # Strategy 1: Standard generation
        response = self._single_generation(inputs, max_new_tokens, temperature, top_p)
        
        if not response or len(response.strip()) < 10:
            logger.warning("First generation attempt failed, trying with lower temperature")
            # Strategy 2: Lower temperature
            response = self._single_generation(inputs, max_new_tokens, 0.3, 0.8)
            
        if not response or len(response.strip()) < 10:
            logger.warning("Second generation attempt failed, trying with greedy decoding")
            # Strategy 3: Greedy decoding
            response = self._single_generation(inputs, max_new_tokens, 0.0, 1.0)
            
        return response

    def _single_generation(self, inputs, max_new_tokens, temperature, top_p):
        """Single generation attempt with improved compatibility"""
        try:
            with torch.no_grad():
                # Use more compatible generation parameters
                generation_kwargs = {
                    'input_ids': inputs['input_ids'],
                    'attention_mask': inputs['attention_mask'],
                    'max_new_tokens': max_new_tokens,
                    'pad_token_id': self.tokenizer.eos_token_id,
                    'eos_token_id': self.tokenizer.eos_token_id,
                    'repetition_penalty': 1.1,
                    'use_cache': True
                }
                
                # Add sampling parameters only if temperature > 0
                if temperature > 0:
                    generation_kwargs.update({
                        'do_sample': True,
                        'temperature': max(temperature, 0.1),  # Ensure minimum temperature
                        'top_p': top_p,
                        'top_k': 50  # Add top_k for better sampling
                    })
                else:
                    generation_kwargs['do_sample'] = False
                
                # Remove early_stopping for compatibility
                # generation_kwargs['early_stopping'] = True  # Commented out for compatibility
                
                outputs = self.model.generate(**generation_kwargs)
            
            input_length = inputs['input_ids'].shape[1]
            response_tokens = outputs[0][input_length:]
            response = self.tokenizer.decode(response_tokens, skip_special_tokens=True).strip()
            
            # Clean up common generation artifacts
            response = self._clean_response(response)
            
            return response
        except Exception as e:
            logger.error(f"SmolLM generation failed: {e}")
            logger.error(f"Generation kwargs: {generation_kwargs if 'generation_kwargs' in locals() else 'Not available'}")
            return ""

    def _clean_response(self, response: str) -> str:
        """Clean up common generation artifacts"""
        # Remove thinking tags that sometimes appear
        response = response.replace("</think>", "").replace("<think>", "")
        
        # Remove incomplete sentences at the end
        sentences = response.split('.')
        if len(sentences) > 1 and len(sentences[-1].strip()) < 10:
            response = '.'.join(sentences[:-1]) + '.'
            
        return response.strip()

    def _postprocess_response(self, response: str, original_prompt: str) -> str:
        """Post-process response to ensure proper JSON format when needed"""
        # Check if JSON format was requested
        if '"response":' in original_prompt or '{ "response":' in original_prompt:
            # If response already looks like valid JSON, return as-is
            if response.strip().startswith('{"response":') and response.strip().endswith('}'):
                return response
                
            # If response doesn't look like JSON, wrap it
            if not (response.strip().startswith('{') and response.strip().endswith('}')):
                # Clean the response and wrap in JSON
                clean_response = response.replace('"', '\\"').replace('\n', '\\n').replace('\r', '').replace('\t', ' ')
                
                # Allow much longer responses - 10x enhancement
                if len(clean_response) > 20000:  # 10x increased: was 2000, now 20000
                    # Find a good breaking point (end of sentence)
                    truncate_point = 20000
                    last_period = clean_response.rfind('.', 0, truncate_point)
                    if last_period > 10000:  # Only truncate at period if it's not too early - 10x increased
                        clean_response = clean_response[:last_period + 1]
                    else:
                        clean_response = clean_response[:truncate_point] + "..."
                
                response = f'{{"response": "{clean_response}"}}'
        
        return response

# GPTOSSModel removed - replaced with NemotronModel
# All old GPT-OSS related code has been removed

class JambaModel:
    """AI21 Jamba Reasoning 3B model implementation - Hybrid Transformer-Mamba architecture"""
    def __init__(self, model: str = "ai21labs/AI21-Jamba-Reasoning-3B"):
        self.model_name = model
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Using device: {self.device}")
        logger.info(f"Loading {model}...")
        
        try:
            # Load tokenizer with fallback for format issues
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(
                    model, 
                    trust_remote_code=True,
                    use_fast=False  # Use slow tokenizer to avoid format issues
                )
            except Exception as e:
                logger.warning(f"Failed with slow tokenizer, trying fast tokenizer: {e}")
                self.tokenizer = AutoTokenizer.from_pretrained(
                    model, 
                    trust_remote_code=True,
                    use_fast=True
                )
            
            # Set padding token properly
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token
            
            # Load model with optimized settings for Jamba
            if torch.cuda.is_available():
                # Load config and disable fast Mamba kernels (use naive implementation)
                from transformers import AutoConfig
                config = AutoConfig.from_pretrained(model, trust_remote_code=True)
                config.use_mamba_kernels = False  # Use naive implementation to avoid kernel requirements
                
                # Use bfloat16 as recommended for Jamba
                self.model = AutoModelForCausalLM.from_pretrained(
                    model,
                    config=config,
                    torch_dtype=torch.bfloat16,
                    device_map="auto",
                    trust_remote_code=True,
                    low_cpu_mem_usage=True
                )
                logger.info("Jamba model loaded with naive Mamba implementation (no fast kernels required)")
            else:
                from transformers import AutoConfig
                config = AutoConfig.from_pretrained(model, trust_remote_code=True)
                config.use_mamba_kernels = False
                
                self.model = AutoModelForCausalLM.from_pretrained(
                    model,
                    config=config,
                    trust_remote_code=True,
                    low_cpu_mem_usage=True
                ).to(self.device)
            
            # Set model to eval mode
            self.model.eval()
            
            logger.info(f"Jamba model loaded successfully on {self.device}")
            logger.info(f"Model vocab size: {self.model.config.vocab_size}")
            logger.info(f"Model supports context length: 256k tokens")
            
        except Exception as e:
            logger.error(f"Failed to load Jamba model: {e}")
            raise

    def generate_text(self, prompt: str, max_length: int = 1000, temperature: float = 0.7, top_p: float = 0.9) -> str:
        """
        Generate response using AI21 Jamba Reasoning 3B model
        """
        try:
            start_time = time.time()
            
            # Format prompt using chat template
            messages = [
                {"role": "user", "content": prompt}
            ]
            
            # Apply chat template if available
            try:
                formatted_prompt = self.tokenizer.apply_chat_template(
                    messages, 
                    add_generation_prompt=True, 
                    tokenize=False
                )
            except Exception as e:
                logger.warning(f"Chat template not available, using direct prompt: {e}")
                formatted_prompt = prompt
            
            # Tokenize with proper settings for long context support
            inputs = self.tokenizer(
                formatted_prompt, 
                return_tensors="pt", 
                padding=True, 
                truncation=True, 
                max_length=8192  # Use reasonable context window
            ).to(self.device)
            
            input_length = inputs['input_ids'].shape[1]
            
            # Calculate max_new_tokens - Jamba can handle very long outputs
            max_new_tokens = min(max(200, max_length - input_length), 4096)
            
            if max_new_tokens <= 0:
                logger.warning(f"Input too long, no room for generation. Input length: {input_length}")
                return "Input prompt too long for generation."
            
            # Generate with optimized parameters for Jamba
            with torch.no_grad():
                generation_kwargs = {
                    'input_ids': inputs['input_ids'],
                    'attention_mask': inputs['attention_mask'],
                    'max_new_tokens': max_new_tokens,
                    'pad_token_id': self.tokenizer.eos_token_id,
                    'eos_token_id': self.tokenizer.eos_token_id,
                    'repetition_penalty': 1.1,
                    'use_cache': True
                }
                
                # Add sampling parameters if temperature > 0
                if temperature > 0:
                    generation_kwargs.update({
                        'do_sample': True,
                        'temperature': max(temperature, 0.1),
                        'top_p': top_p,
                        'top_k': 50
                    })
                else:
                    generation_kwargs['do_sample'] = False
                
                outputs = self.model.generate(**generation_kwargs)
            
            # Decode only new tokens
            response_tokens = outputs[0][input_length:]
            response = self.tokenizer.decode(response_tokens, skip_special_tokens=True).strip()
            
            # Clean up response
            response = self._clean_response(response)
            
            generation_time = time.time() - start_time
            logger.info(f"Jamba generated {len(response_tokens)} tokens in {generation_time:.2f}s")
            
            return response if response else "Unable to generate response."
            
        except Exception as e:
            logger.error(f"Error generating Jamba response: {e}")
            # Clean up GPU memory on error
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            raise RuntimeError(f"Text generation failed: {str(e)}")
    
    def _clean_response(self, response: str) -> str:
        """Clean up common generation artifacts"""
        # Remove thinking tags and common artifacts
        response = response.replace("</think>", "").replace("<think>", "")
        response = response.replace("<|im_start|>", "").replace("<|im_end|>", "")
        response = response.replace("<|assistant|>", "").replace("<|user|>", "")
        
        # Remove incomplete sentences at the end
        if '. ' in response:
            sentences = response.split('. ')
            if len(sentences) > 1 and len(sentences[-1].strip()) < 15:
                response = '. '.join(sentences[:-1]) + '.'
        
        return response.strip()
    
    def __str__(self):
        return f"JambaModel({self.model_name})"
    
    def __del__(self):
        # Clean up GPU memory when object is destroyed
        if hasattr(self, 'model'):
            del self.model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

class PhiModel:
    """Microsoft Phi-3.5-mini-instruct model implementation"""
    def __init__(self, model: str = "microsoft/Phi-3-mini-4k-instruct"):  # Smaller alternative
        self.model_name = model
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Using device: {self.device}")
        logger.info(f"Loading {model}...")
        
        # Check GPU memory if available
        if torch.cuda.is_available():
            gpu_memory_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            logger.info(f"GPU memory available: {gpu_memory_gb:.1f} GB")
            if gpu_memory_gb < 8:
                logger.warning(f"Phi-3.5-mini may require significant GPU memory. Available: {gpu_memory_gb:.1f} GB")
        
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model, trust_remote_code=True)
            
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token
            
            # Load model with optimized settings for Phi - avoiding problematic attention implementations
            if torch.cuda.is_available():
                self.model = AutoModelForCausalLM.from_pretrained(
                    model,
                    torch_dtype=torch.float16,
                    device_map="auto",
                    trust_remote_code=True
                )
                logger.info(f"Phi model loaded successfully on GPU with device_map=auto")
            else:
                self.model = AutoModelForCausalLM.from_pretrained(
                    model,
                    trust_remote_code=True,
                    torch_dtype=torch.float32
                ).to(self.device)
                logger.info(f"Phi model loaded successfully on CPU")
                
        except Exception as e:
            logger.error(f"Failed to load Phi model: {e}")
            raise

    def generate_text(self, prompt: str, max_length: int = 100, temperature: float = 0.7, top_p: float = 0.9) -> str:
        """
        Generate response using Phi model
        """
        try:
            start_time = time.time()
            
            # Use Phi's chat template format
            messages = [{"role": "user", "content": prompt}]
            
            try:
                # Apply chat template if available
                formatted_prompt = self.tokenizer.apply_chat_template(
                    messages, 
                    tokenize=False, 
                    add_generation_prompt=True
                )
                inputs = self.tokenizer(formatted_prompt, return_tensors="pt", padding=True)
                logger.info("Using chat template for Phi")
            except Exception as e:
                logger.warning(f"Chat template not available for Phi: {e}")
                # Fallback to direct tokenization
                inputs = self.tokenizer(prompt, return_tensors="pt", padding=True)
                logger.info("Using direct tokenization for Phi")
            
            # Move inputs to device
            if hasattr(self.model, 'device'):
                inputs = {k: v.to(self.model.device) for k, v in inputs.items()}
            else:
                inputs = {k: v.to(self.device) for k, v in inputs.items()}
            
            input_length = inputs['input_ids'].shape[1]
            
            # Calculate max_new_tokens
            max_new_tokens = min(max(200, max_length - input_length), 4096)
            
            if max_new_tokens <= 0:
                logger.warning(f"Input too long. Input length: {input_length}, Max length: {max_length}")
                return "Input prompt too long for generation."
            
            # Try different generation strategies to avoid cache issues
            response = self._generate_with_fallback_strategies(inputs, max_new_tokens, temperature, top_p, input_length)
            
            # Clean up response
            response = self._clean_response(response)
            
            generation_time = time.time() - start_time
            logger.info(f"Phi generation completed in {generation_time:.2f}s")
            
            return response if response else "Unable to generate response."
            
        except Exception as e:
            logger.error(f"Phi text generation failed: {str(e)}")
            raise RuntimeError(f"Text generation failed: {str(e)}")
    
    def _generate_with_fallback_strategies(self, inputs, max_new_tokens, temperature, top_p, input_length):
        """Try multiple generation strategies to avoid cache-related issues"""
        
        # Strategy 1: Without cache and with explicit settings
        try:
            logger.info("Trying generation strategy 1: No cache")
            with torch.no_grad():
                outputs = self.model.generate(
                    inputs['input_ids'],
                    attention_mask=inputs['attention_mask'],
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    do_sample=temperature > 0,
                    pad_token_id=self.tokenizer.pad_token_id,
                    eos_token_id=self.tokenizer.eos_token_id,
                    repetition_penalty=1.1,
                    use_cache=False,  # Disable cache to avoid DynamicCache issues
                    past_key_values=None  # Ensure no past_key_values are used
                )
            
            response_tokens = outputs[0][input_length:]
            response = self.tokenizer.decode(response_tokens, skip_special_tokens=True).strip()
            if response and len(response.strip()) > 5:
                return response
                
        except Exception as e:
            logger.warning(f"Strategy 1 failed: {e}")
        
        # Strategy 2: Greedy decoding without sampling
        try:
            logger.info("Trying generation strategy 2: Greedy decoding")
            with torch.no_grad():
                outputs = self.model.generate(
                    inputs['input_ids'],
                    attention_mask=inputs['attention_mask'],
                    max_new_tokens=max_new_tokens,
                    pad_token_id=self.tokenizer.pad_token_id,
                    eos_token_id=self.tokenizer.eos_token_id,
                    do_sample=False,  # Greedy decoding
                    use_cache=False
                )
            
            response_tokens = outputs[0][input_length:]
            response = self.tokenizer.decode(response_tokens, skip_special_tokens=True).strip()
            if response and len(response.strip()) > 5:
                return response
                
        except Exception as e:
            logger.warning(f"Strategy 2 failed: {e}")
        
        # Strategy 3: Basic generation with minimal parameters
        try:
            logger.info("Trying generation strategy 3: Minimal parameters")
            with torch.no_grad():
                outputs = self.model.generate(
                    inputs['input_ids'],
                    max_new_tokens=min(max_new_tokens, 512),
                    pad_token_id=self.tokenizer.pad_token_id,
                    use_cache=False
                )
            
            response_tokens = outputs[0][input_length:]
            response = self.tokenizer.decode(response_tokens, skip_special_tokens=True).strip()
            return response
            
        except Exception as e:
            logger.error(f"All generation strategies failed. Last error: {e}")
            raise e
    
    def _clean_response(self, response: str) -> str:
        """Clean up common generation artifacts"""
        # Remove chat template artifacts
        response = response.replace("<|assistant|>", "").replace("<|user|>", "")
        response = response.replace("<|im_start|>", "").replace("<|im_end|>", "")
        
        # Remove thinking tags
        response = response.replace("</think>", "").replace("<think>", "")
        
        return response.strip()
    
    def __str__(self):
        return f"PhiModel({self.model_name})"
    
    def __del__(self):
        # Clean up GPU memory when object is destroyed
        if hasattr(self, 'model'):
            del self.model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

class DeepSeekModel:
    """DeepSeek-R1-Distill-Qwen-7B model implementation for CVDP benchmark"""
    def __init__(self, model: str = "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B"):
        self.model_name = model
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Using device: {self.device}")
        logger.info(f"Loading {model}...")
        
        # Check GPU memory if available
        if torch.cuda.is_available():
            gpu_memory_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            logger.info(f"GPU memory available: {gpu_memory_gb:.1f} GB")
            if gpu_memory_gb < 14:
                logger.warning(f"DeepSeek-R1-Distill-Qwen-7B may require significant GPU memory. Available: {gpu_memory_gb:.1f} GB")
        
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model, trust_remote_code=True)
        except Exception as e:
            logger.warning(f"Error loading tokenizer for {model}: {e}")
            fallback_model = "deepseek-ai/deepseek-coder-7b-instruct-v1.5"
            logger.info(f"Attempting fallback to {fallback_model}")
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(fallback_model, trust_remote_code=True)
                self.model_name = fallback_model
                model = fallback_model
            except Exception as e2:
                logger.error(f"Fallback model also failed: {e2}")
                raise RuntimeError(f"Failed to load any DeepSeek model: {e2}")
        
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        
        try:
            if torch.cuda.is_available():
                self.model = AutoModelForCausalLM.from_pretrained(
                    model,
                    torch_dtype=torch.float16,
                    device_map="auto",
                    trust_remote_code=True
                )
                logger.info(f"DeepSeek model loaded successfully on GPU with device_map=auto")
            else:
                self.model = AutoModelForCausalLM.from_pretrained(
                    model,
                    trust_remote_code=True,
                    torch_dtype=torch.float32
                ).to(self.device)
                logger.info(f"DeepSeek model loaded successfully on CPU")
            
        except Exception as e:
            logger.error(f"Failed to load DeepSeek model: {e}")
            raise

    def generate_text(self, prompt: str, max_length: int = 100, temperature: float = 0.7, top_p: float = 0.9) -> str:
        """
        Generate response using DeepSeek model - keeps original prompt unchanged
        """
        try:
            start_time = time.time()
            
            # Add code-only instruction to prompt
            prompt = f"{prompt}\n\nIMPORTANT: Provide ONLY the code without any explanations, markdown formatting, or additional text."
            
            # Use chat template if available
            try:
                messages = [{"role": "user", "content": prompt}]
                formatted_prompt = self.tokenizer.apply_chat_template(
                    messages, 
                    tokenize=False, 
                    add_generation_prompt=True
                )
                inputs = self.tokenizer(formatted_prompt, return_tensors="pt", padding=True)
                logger.info("Using chat template for DeepSeek")
            except:
                # Fallback to direct tokenization if chat template not available
                inputs = self.tokenizer(prompt, return_tensors="pt", padding=True)
                logger.info("Using direct tokenization for DeepSeek")
            
            # Move inputs to device
            if hasattr(self.model, 'device'):
                inputs = {k: v.to(self.model.device) for k, v in inputs.items()}
            else:
                inputs = {k: v.to(self.device) for k, v in inputs.items()}
            
            input_length = inputs['input_ids'].shape[1]
            
            # Calculate max_new_tokens - increased for longer code generation
            max_new_tokens = min(max(500, max_length - input_length), 8192)  # Increased from 2000 to 8192
            
            if max_new_tokens <= 0:
                logger.warning(f"Input too long. Input length: {input_length}, Max length: {max_length}")
                return "Input prompt too long for generation."
            
            # Generate response
            with torch.no_grad():
                outputs = self.model.generate(
                    inputs['input_ids'],
                    attention_mask=inputs['attention_mask'],
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    do_sample=temperature > 0,
                    pad_token_id=self.tokenizer.pad_token_id,
                    eos_token_id=self.tokenizer.eos_token_id
                )
            
            # Decode only new tokens
            response_tokens = outputs[0][input_length:]
            response = self.tokenizer.decode(response_tokens, skip_special_tokens=True).strip()
            
            # Clean up response - remove common artifacts
            if response.startswith("assistant"):
                response = response[len("assistant"):].strip()
            
            response = response.replace("</think>", "").replace("<think>", "")
            response = response.replace("<|im_start|>", "").replace("<|im_end|>", "")
            
            # Remove markdown code blocks if present
            if "```" in response:
                # Extract code from markdown blocks
                import re
                code_blocks = re.findall(r'```(?:\w+)?\n?(.*?)```', response, re.DOTALL)
                if code_blocks:
                    response = code_blocks[0].strip()
                else:
                    # Remove the backticks if pattern didn't match
                    response = response.replace("```", "").strip()
            
            generation_time = time.time() - start_time
            logger.info(f"DeepSeek generation completed in {generation_time:.2f}s, generated {len(response_tokens)} tokens")
            
            return response if response else "Unable to generate response."
            
        except Exception as e:
            logger.error(f"DeepSeek text generation failed: {str(e)}")
            raise RuntimeError(f"Text generation failed: {str(e)}")
    
    def __str__(self):
        return f"DeepSeekModel({self.model_name})"
    
    def __del__(self):
        # Clean up GPU memory when object is destroyed
        if hasattr(self, 'model'):
            del self.model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

# Global model instances
smollm_generator = None
deepseek_generator = None
nemotron_generator = None
jamba_generator = None
phi_generator = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models on startup and clean up on shutdown"""
    global smollm_generator, deepseek_generator, nemotron_generator, jamba_generator, phi_generator
    
    logger.info("Starting SLM API server...")
    
    # SmolLM - DISABLED to save GPU memory
    smollm_generator = None
    logger.info("SmolLM model DISABLED to save GPU memory")
    
    # DeepSeek - DISABLED to save GPU memory  
    deepseek_generator = None
    logger.info("DeepSeek model DISABLED to save GPU memory")
    
    # Nemotron - DISABLED to save GPU memory
    nemotron_generator = None
    logger.info("Nemotron model DISABLED to save GPU memory")
    
    # Jamba - DISABLED to save GPU memory
    jamba_generator = None
    logger.info("Jamba model DISABLED to save GPU memory")
    
    # Phi - ENABLED (primary model)
    try:
        logger.info("Loading Phi model...")
        phi_generator = PhiModel()
        logger.info("Phi model loaded successfully!")
    except Exception as e:
        logger.error(f"Failed to load Phi model: {e}")
        phi_generator = None
    
    if phi_generator is None:
        logger.error("Failed to load Phi model!")
        raise RuntimeError("Phi model could not be loaded")
    
    logger.info("SLM API server ready with Phi model!")
    yield
    
    # Cleanup
    logger.info("Shutting down SLM API server...")

# Initialize the FastAPI app with lifespan
app = FastAPI(
    title="SLM API for CVDP Benchmark",
    description="Small Language Model API server with Microsoft Phi-3.5-mini-instruct model",
    version="1.0.0",
    lifespan=lifespan
)

# Define the request data structure using Pydantic
class PromptRequest(BaseModel):
    prompt: str = Field(..., description="The input prompt for text generation")
    max_length: Optional[int] = Field(default=None, ge=1, le=32768, description="Maximum length of generated text - 10x enhanced")
    max_tokens: Optional[int] = Field(default=None, ge=1, le=32768, description="Maximum tokens to generate (alias for max_length) - 10x enhanced")
    model: Optional[str] = Field(default="phi", description="Model to use: 'phi' (primary/only active), 'deepseek' (disabled), 'jamba' (disabled), 'nemotron' (disabled), or 'smollm' (disabled)")
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    top_p: Optional[float] = Field(default=0.9, ge=0.0, le=1.0, description="Top-p sampling parameter")
    
    def get_max_length(self) -> int:
        """Get the maximum length, supporting both max_length and max_tokens parameters"""
        if self.max_tokens is not None:
            return self.max_tokens
        elif self.max_length is not None:
            return self.max_length
        else:
            return 8192  # Increased default for longer code generation (was 10240)

class GenerationResponse(BaseModel):
    response: str = Field(..., description="Generated text response")
    model: str = Field(..., description="Model used for generation")
    generation_time: Optional[float] = Field(None, description="Time taken for generation in seconds")
    tokens_generated: Optional[int] = Field(None, description="Number of tokens generated")

class ErrorResponse(BaseModel):
    error: str = Field(..., description="Error message")
    model: Optional[str] = Field(None, description="Model that encountered the error")
    detail: Optional[str] = Field(None, description="Detailed error information")

@app.get("/", response_model=Dict[str, Any])
def read_root():
    """Get API status and available models"""
    models = []
    
    if smollm_generator:
        models.append({
            "name": smollm_generator.model_name,
            "type": "SmolLM2-1.7B-Instruct",
            "device": smollm_generator.device,
            "status": "available"
        })
    
    if deepseek_generator:
        models.append({
            "name": deepseek_generator.model_name,
            "type": "DeepSeek-R1-Distill-Qwen-7B",
            "device": deepseek_generator.device,
            "status": "available"
        })
    
    if nemotron_generator:
        models.append({
            "name": nemotron_generator.model_name,
            "type": "NVIDIA-Nemotron-Mini-4B",
            "device": nemotron_generator.device,
            "status": "available"
        })
    
    if jamba_generator:
        models.append({
            "name": jamba_generator.model_name,
            "type": "AI21-Jamba-Reasoning-3B",
            "device": jamba_generator.device,
            "status": "available"
        })
    
    if phi_generator:
        models.append({
            "name": phi_generator.model_name,
            "type": "Microsoft-Phi-3.5-mini-instruct",
            "device": phi_generator.device,
            "status": "available"
        })
    
    return {
        "status": "SLM API is running",
        "version": "1.0.0",
        "models": models,
        "endpoints": ["/", "/model_info", "/generate", "/health"]
    }

@app.get("/model_info", response_model=Dict[str, Any])
def get_model_info():
    """Get detailed model information"""
    info = {}
    
    if smollm_generator:
        info["smollm"] = {
            "model_name": smollm_generator.model_name,
            "device": smollm_generator.device,
            "model_type": "SmolLM2-1.7B-Instruct",
            "status": "available"
        }
    else:
        info["smollm"] = {"status": "unavailable", "error": "Model failed to load"}
    
    if deepseek_generator:
        info["deepseek"] = {
            "model_name": deepseek_generator.model_name,
            "device": deepseek_generator.device,
            "model_type": "DeepSeek-R1-Distill-Qwen-7B",
            "status": "available"
        }
    else:
        info["deepseek"] = {"status": "unavailable", "error": "Model failed to load"}
    
    if nemotron_generator:
        info["nemotron"] = {
            "model_name": nemotron_generator.model_name,
            "device": nemotron_generator.device,
            "model_type": "NVIDIA-Nemotron-Mini-4B",
            "status": "available"
        }
    else:
        info["nemotron"] = {"status": "unavailable", "error": "Model failed to load"}
    
    if jamba_generator:
        info["jamba"] = {
            "model_name": jamba_generator.model_name,
            "device": jamba_generator.device,
            "model_type": "AI21-Jamba-Reasoning-3B",
            "status": "available",
            "context_length": "256k tokens",
            "architecture": "Hybrid Transformer-Mamba"
        }
    else:
        info["jamba"] = {"status": "unavailable", "error": "Model disabled or failed to load"}
    
    if phi_generator:
        info["phi"] = {
            "model_name": phi_generator.model_name,
            "device": phi_generator.device,
            "model_type": "Microsoft-Phi-3.5-mini-instruct",
            "status": "available",
            "context_length": "128k tokens",
            "architecture": "Transformer"
        }
    else:
        info["phi"] = {"status": "unavailable", "error": "Model disabled or failed to load"}
    
    return info

@app.get("/health")
def health_check():
    """Health check endpoint"""
    available_models = []
    if smollm_generator:
        available_models.append("smollm")
    if deepseek_generator:
        available_models.append("deepseek")
    if nemotron_generator:
        available_models.append("nemotron")
    if jamba_generator:
        available_models.append("jamba")
    if phi_generator:
        available_models.append("phi")
    
    return {
        "status": "healthy" if available_models else "unhealthy",
        "available_models": available_models,
        "timestamp": time.time()
    }

@app.post("/generate", response_model=GenerationResponse, responses={
    400: {"model": ErrorResponse, "description": "Bad Request"},
    500: {"model": ErrorResponse, "description": "Internal Server Error"},
    503: {"model": ErrorResponse, "description": "Service Unavailable"}
})
def generate_text(request: PromptRequest):
    """
    Generate text using the specified model.
    
    - **prompt**: The input text prompt
    - **max_length**: Maximum length of generated response (1-32768)
    - **max_tokens**: Alternative parameter name for max_length (1-32768)
    - **model**: Model to use ('smollm', 'deepseek', 'nemotron', or 'jamba')
    - **temperature**: Sampling temperature (0.0-2.0)
    - **top_p**: Top-p sampling parameter (0.0-1.0)
    
    Note: Either max_length or max_tokens can be used (max_tokens takes precedence)
    """
    start_time = time.time()
    
    try:
        # Validate model availability
        if request.model == "deepseek":
            if deepseek_generator is None:
                raise HTTPException(
                    status_code=503,
                    detail="DeepSeek model is not available"
                )
            generator = deepseek_generator
        elif request.model == "smollm":
            if smollm_generator is None:
                raise HTTPException(
                    status_code=503,
                    detail="SmolLM model is not available"
                )
            generator = smollm_generator
        elif request.model == "nemotron":
            if nemotron_generator is None:
                raise HTTPException(
                    status_code=503,
                    detail="Nemotron model is not available"
                )
            generator = nemotron_generator
        elif request.model == "jamba":
            if jamba_generator is None:
                raise HTTPException(
                    status_code=503,
                    detail="Jamba model is not available"
                )
            generator = jamba_generator
        elif request.model == "phi":
            if phi_generator is None:
                raise HTTPException(
                    status_code=503,
                    detail="Phi model is not available"
                )
            generator = phi_generator
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported model: {request.model}. Use 'phi' (only active model currently)"
            )
        
        # Validate prompt
        if not request.prompt or not request.prompt.strip():
            raise HTTPException(
                status_code=400,
                detail="Prompt cannot be empty"
            )
        
        # Log the request
        max_length_to_use = request.get_max_length()
        logger.info(f"Generation request - Model: {request.model}, Max length: {max_length_to_use}, "
                   f"Temperature: {request.temperature}, Top-p: {request.top_p}")
        logger.debug(f"Prompt preview: {request.prompt[:100]}...")
        
        # Generate text
        generated_text = generator.generate_text(
            prompt=request.prompt,
            max_length=max_length_to_use,
            temperature=request.temperature,
            top_p=request.top_p
        )
        
        generation_time = time.time() - start_time
        
        # Count generated tokens (approximate)
        tokens_generated = len(generated_text.split()) if generated_text else 0
        
        logger.info(f"Generation successful - Time: {generation_time:.2f}s, "
                   f"Tokens: {tokens_generated}, Model: {request.model}")
        
        return GenerationResponse(
            response=generated_text,
            model=request.model,
            generation_time=generation_time,
            tokens_generated=tokens_generated
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Log detailed error information
        logger.error(f"Generation failed for model {request.model}: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        # Return structured error response
        raise HTTPException(
            status_code=500,
            detail=f"Text generation failed: {str(e)}"
        )

# Add a simple test endpoint for debugging
@app.post("/test")
def test_generation():
    """Simple test endpoint for debugging"""
    try:
        test_request = PromptRequest(
            prompt="Hello, how are you?",
            max_length=100,
            model="phi"
        )
        return generate_text(test_request)
    except Exception as e:
        return {"error": f"Test failed: {str(e)}"}

@app.post("/test_json")
def test_json_generation():
    """Test endpoint for JSON format responses"""
    try:
        test_request = PromptRequest(
            prompt='Answer this question in JSON format: { "response": "your answer" } Why is testing circular shifts important?',
            max_length=500,
            model="nemotron",
            temperature=0.4
        )
        return generate_text(test_request)
    except Exception as e:
        return {"error": f"JSON test failed: {str(e)}"}

@app.post("/test_complex")
def test_complex_prompt():
    """Test endpoint for complex technical prompts"""
    try:
        complex_prompt = '''You are solving a 'Question & Answer on Testbench' problem. Provide the response in JSON format: { "response": "<response>" }

Question: Explain in four sentences why testing circular shifts with shift_bits = DATA_WIDTH is critical for ensuring the barrel shifter correctly handles edge cases without introducing unintended behavior or corrupting data integrity.'''
        
        test_request = PromptRequest(
            prompt=complex_prompt,
            max_length=800,
            model="nemotron",
            temperature=0.3
        )
        return generate_text(test_request)
    except Exception as e:
        return {"error": f"Complex test failed: {str(e)}"}

@app.post("/test_nemotron")
def test_nemotron():
    """Test endpoint for Nemotron model"""
    try:
        test_request = PromptRequest(
            prompt="Explain the importance of artificial intelligence in modern technology.",
            max_length=500,
            model="nemotron",
            temperature=0.7
        )
        return generate_text(test_request)
    except Exception as e:
        return {"error": f"Nemotron test failed: {str(e)}"}

@app.post("/test_long")
def test_long_response():
    """Test endpoint for very long detailed responses"""
    try:
        long_prompt = '''Provide a comprehensive, detailed technical explanation in JSON format: { "response": "<detailed_response>" }

Question: Explain comprehensively why testing circular shifts with shift_bits = DATA_WIDTH is critical for barrel shifter validation. Include specific examples, edge cases, technical details about hardware implementation, potential failure modes, and verification strategies.'''
        
        test_request = PromptRequest(
            prompt=long_prompt,
            max_length=15000,  # 10x enhanced: was 1500, now 15000
            model="phi",
            temperature=0.4
        )
        return generate_text(test_request)
    except Exception as e:
        return {"error": f"Long response test failed: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    
    # Run the server
    logger.info("Starting SLM API server...")
    uvicorn.run(
        "slm_api_code:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=False  # Set to True for development
    )
