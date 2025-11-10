# hf_service.py
import os
import json
import requests
from typing import Optional

HF_API_TOKEN = os.getenv("HF_API_TOKEN")
HF_MODEL = os.getenv("HF_MODEL", "meta-llama/Meta-Llama-3-8B-Instruct")

# ✅ FIXED URL (no /hf-inference/models)
INFERENCE_URL = f"https://router.huggingface.co/{HF_MODEL}"

HEADERS = {
    "Authorization": f"Bearer {HF_API_TOKEN}",
    "Content-Type": "application/json"
}

class HFError(RuntimeError):
    pass

def _post_json(payload: dict) -> dict:
    response = requests.post(
        INFERENCE_URL,
        headers=HEADERS,
        data=json.dumps(payload),
        timeout=120
    )
    if response.status_code != 200:
        raise HFError(f"HF Inference error {response.status_code}: {response.text[:500]}")
    try:
        return response.json()
    except Exception as e:
        raise HFError(f"HF returned non-JSON: {response.text[:500]} ({e})")

def generate_text(prompt: str, max_new_tokens: int = 512, temperature: float = 0.4) -> str:
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": max_new_tokens,
            "temperature": temperature,
            "return_full_text": False
        }
    }
    data = _post_json(payload)
    if isinstance(data, list) and data and "generated_text" in data[0]:
        return data[0]["generated_text"]
    if isinstance(data, dict) and "generated_text" in data:
        return data["generated_text"]
    return json.dumps(data)

def generate_json(prompt: str, max_new_tokens: int = 800, temperature: float = 0.2) -> dict:
    raw_output = generate_text(prompt, max_new_tokens=max_new_tokens, temperature=temperature)
    cleaned = raw_output.strip().strip("`")

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        import re
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise HFError(f"Could not parse JSON from model output: {raw_output[:500]}")
