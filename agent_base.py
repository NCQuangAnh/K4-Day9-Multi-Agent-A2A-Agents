"""
agent_base.py - Base agent class with Groq LLM integration and tracing.
"""

import json
import time
import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# Model name hardcoded per assignment requirement (not in .env)
MODEL_NAME = "llama-3.1-8b-instant"

# Global trace log
_trace_entries = []


def get_trace_entries():
    """Return all trace entries collected during the run."""
    return _trace_entries


def clear_trace_entries():
    """Clear all trace entries."""
    _trace_entries.clear()


class BaseAgent:
    """Base class for all agents in the multi-agent system."""

    def __init__(self, name: str, role: str):
        self.name = name
        self.role = role
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    def call_llm(self, system_prompt: str, user_prompt: str, max_retries: int = 3) -> str:
        """
        Call Groq LLM with retry logic and trace logging.
        Returns the text content of the LLM response.
        """
        for attempt in range(max_retries):
            try:
                start_time = time.time()
                response = self.client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.1,
                    max_tokens=4096,
                )
                elapsed = time.time() - start_time
                result = response.choices[0].message.content

                # Log trace entry
                trace_entry = {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "agent": self.name,
                    "model": MODEL_NAME,
                    "input_tokens": response.usage.prompt_tokens if response.usage else None,
                    "output_tokens": response.usage.completion_tokens if response.usage else None,
                    "latency_ms": round(elapsed * 1000, 2),
                    "status": "success",
                }
                _trace_entries.append(trace_entry)

                return result

            except Exception as e:
                wait_time = 2 ** attempt
                print(f"[{self.name}] LLM call failed (attempt {attempt + 1}/{max_retries}): {e}")

                trace_entry = {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "agent": self.name,
                    "model": MODEL_NAME,
                    "error": str(e),
                    "status": "error",
                    "retry_attempt": attempt + 1,
                }
                _trace_entries.append(trace_entry)

                if attempt < max_retries - 1:
                    time.sleep(wait_time)
                else:
                    raise

    def log_action(self, case_id: str, action: str, details: dict = None):
        """Log a non-LLM action to the trace."""
        trace_entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "agent": self.name,
            "case_id": case_id,
            "action": action,
            "details": details or {},
            "status": "success",
        }
        _trace_entries.append(trace_entry)
