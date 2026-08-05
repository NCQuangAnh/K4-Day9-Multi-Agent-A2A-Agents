"""
agent_base.py - Base Agent wrapper for Groq LLM API with retry logic and trace logging.
"""

import os
import json
import time
from dotenv import load_dotenv
from groq import Groq

# Load environment variables from .env file
load_dotenv()

# Model specifications
DEFAULT_MODEL = "allam-2-7b"
PARAMETER_SIZE = "7B"

GLOBAL_TRACE_LOG = []


def log_global_trace(entry: dict):
    GLOBAL_TRACE_LOG.append(entry)


def get_trace_entries() -> list:
    return GLOBAL_TRACE_LOG


def clear_trace_entries():
    GLOBAL_TRACE_LOG.clear()


class BaseAgent:
    """Base class for all AI agents in the system."""

    def __init__(self, name: str, role: str, model_name: str = DEFAULT_MODEL):
        self.name = name
        self.role = role
        self.model_name = model_name

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable is missing in .env")

        self.client = Groq(api_key=api_key)

    def log_action(self, case_id: str, action: str, details: dict = None):
        """Record an agent action in the global trace log."""
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "case_id": case_id,
            "agent_name": self.name,
            "agent_role": self.role,
            "action": action,
            "details": details or {},
        }
        log_global_trace(entry)

    def call_llm(
        self,
        prompt: str,
        system_prompt: str = None,
        temperature: float = 0.1,
        max_retries: int = 3,
    ) -> str:
        """Call Groq API with exponential backoff retry logic."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=1024,
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                print(f"[{self.name}] LLM call error (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise e
