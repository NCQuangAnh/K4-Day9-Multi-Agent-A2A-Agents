import json
from typing import Any, Dict, Optional

from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline

from model_config import MODEL_NAME, MAX_NEW_TOKENS, TEMPERATURE, FALLBACK_MODEL_NAME


class LLMClient:
    def __init__(self, model_name: str = MODEL_NAME):
        self.model_name = model_name
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
            self.model = AutoModelForCausalLM.from_pretrained(
                model_name,
                device_map="auto",
                torch_dtype="auto",
            )
            self.pipeline = pipeline(
                "text-generation",
                model=self.model,
                tokenizer=self.tokenizer,
                max_new_tokens=MAX_NEW_TOKENS,
                temperature=TEMPERATURE,
                do_sample=False,
            )
        except Exception:
            self.tokenizer = AutoTokenizer.from_pretrained(FALLBACK_MODEL_NAME)
            self.model = AutoModelForCausalLM.from_pretrained(FALLBACK_MODEL_NAME)
            self.pipeline = pipeline(
                "text-generation",
                model=self.model,
                tokenizer=self.tokenizer,
                max_new_tokens=MAX_NEW_TOKENS,
                temperature=TEMPERATURE,
                do_sample=False,
            )

    def generate(self, prompt: str) -> str:
        result = self.pipeline(prompt, max_new_tokens=MAX_NEW_TOKENS)
        return result[0]["generated_text"]

    def generate_json(self, prompt: str) -> Optional[Dict[str, Any]]:
        text = self.generate(prompt)
        try:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1:
                return None
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
