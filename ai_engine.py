from __future__ import annotations

import json
import os
import re
import urllib.request

AI_PROVIDER = os.getenv("AI_PROVIDER", "none").strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite").strip()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3").strip()


def _json_request(url, payload, headers=None, timeout=45):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def extract_job_intelligence(title, description):
    """Optional enrichment. Returns {} when AI is unavailable; never blocks discovery."""
    if AI_PROVIDER == "none":
        return {}

    prompt = f"""Extract job requirements from this listing. Return ONLY valid JSON.
Schema:
{{"role":"string","seniority":"string","experience_years":number|null,"required_skills":["string"],"nice_to_have":["string"],"location":["string"],"remote":true|false,"salary_min_lpa":number|null,"salary_max_lpa":number|null}}
Job title: {title}
Description:
{description[:12000]}
"""
    try:
        if AI_PROVIDER == "ollama":
            data = _json_request(
                f"{OLLAMA_BASE_URL}/api/generate",
                {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "format": "json"},
                timeout=90,
            )
            return json.loads(data.get("response", "{}"))
        if AI_PROVIDER == "gemini" and GEMINI_API_KEY:
            data = _json_request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}",
                {"contents":[{"parts":[{"text":prompt}]}],
                 "generationConfig":{"responseMimeType":"application/json","temperature":0}},
                timeout=60,
            )
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
    except Exception:
        return {}
    return {}
