import os

MODEL_NAME = os.getenv("LLM_MODEL_NAME", "meta-llama/Llama-2-7b-chat-hf")
MAX_NEW_TOKENS = int(os.getenv("LLM_MAX_NEW_TOKENS", "256"))
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
FALLBACK_MODEL_NAME = os.getenv("LLM_FALLBACK_MODEL_NAME", "gpt2")
