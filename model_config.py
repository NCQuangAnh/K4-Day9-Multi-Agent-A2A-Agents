"""Model declaration for the optional local multi-agent reasoning layer.

The policy calculations in ``pipeline.py`` remain deterministic so that every
refund, evidence ID, and timestamp is directly reproducible from the Olist CSV
files.  A local agent runtime can use this model to summarize its findings or
coordinate handoffs, but it must not invent unsupported evidence.
"""

MODEL_NAME = "Qwen2.5-7B-Instruct"
MODEL_PARAMETER_SIZE = "7B"
MODEL_PROVIDER = "Ollama-compatible local runtime"
MODEL_ROLE = "Coordinator and evidence-summary agents"
MAX_TOKENS = 1024
TEMPERATURE = 0.0

