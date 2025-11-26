# backend/llm_gemini.py
"""
Robust LangChain-compatible Gemini wrapper.
This file attempts to import types from multiple LangChain layouts and falls back to
lightweight local definitions if necessary. Should work across LangChain v0.1x -> v1.x.
"""

from pydantic import BaseModel
from typing import Optional, List, Deque, Tuple
from collections import deque
from dotenv import load_dotenv
import os

load_dotenv()  # load .env if present

# --- Robust imports for BaseLLM / BaseChatModel --------------------------------
BaseLLM = None
_base_import_err = None
try:
    # LangChain v1.x split: langchain_core
    from langchain_core.language_models import BaseLLM
except Exception as e:
    _base_import_err = e
    try:
        # older v0.x layouts
        from langchain.llms.base import LLM as BaseLLM
    except Exception:
        BaseLLM = None

if BaseLLM is None:
    raise ImportError(
        "Could not import LangChain BaseLLM/LLM. "
        "Ensure 'langchain' or 'langchain-core' is installed in the active venv."
    )

# --- Robust imports for LLMResult, Generation ----------------------------------
LLMResult = None
Generation = None
try:
    # try langchain_core (v1.x)
    from langchain_core.schema import LLMResult, Generation
except Exception:
    try:
        # older langchain locations
        from langchain.schema import LLMResult, Generation
    except Exception:
        # Fallback simple local stand-ins (duck-typed)
        from dataclasses import dataclass

        @dataclass
        class Generation:
            text: str

        @dataclass
        class LLMResult:
            generations: list

# --- The actual wrapper class -------------------------------------------------
class GeminiLLM(BaseLLM, BaseModel):
    """
    LangChain-compatible LLM wrapper for Google Gemini (genai).
    Resistant to LangChain layout differences.
    Keeps a simple per-instance deque memory (last N turns).
    """

    model_name: str = "gemini-2.5-flash"
    temperature: float = 0.2
    max_output_tokens: int = 1024
    context_window: int = 5  # keep last N turns

    def __init__(self, **data):
        super().__init__(**data)
        # per-instance simple memory: deque of (user_prompt, assistant_response)
        self._memory: Deque[Tuple[str, str]] = deque(maxlen=self.context_window)

    def _build_prompt_with_memory(self, prompt: str) -> str:
        pieces = []
        for user_turn, assistant_turn in self._memory:
            pieces.append(f"User: {user_turn}")
            pieces.append(f"Assistant: {assistant_turn}")
        pieces.append(f"User: {prompt}")
        return "\n".join(pieces)

    def _call(self, prompt: str, stop: Optional[List[str]] = None) -> str:
        """
        Simple synchronous call that returns assistant text for a single prompt.
        """
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set in environment (set in .env or env vars)")

        composed_prompt = self._build_prompt_with_memory(prompt)

        # Lazy import google genai SDK (keeps requirements optional until runtime)
        from google import genai
        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model=self.model_name,
            contents=composed_prompt
        )

        # Extract text robustly
        text = getattr(response, "text", None)
        if text is None:
            try:
                text = response.text()
            except Exception:
                text = str(response)

        # Save into memory (best-effort)
        try:
            self._memory.append((prompt, text))
        except Exception:
            pass

        return text

    def _generate(self, prompts: List[str], stop: Optional[List[str]] = None, run_manager=None):
        """
        Required by newer LangChain BaseLLM implementations: return an LLMResult-like
        object with `generations` being a list (per prompt) of Generation(s).
        We call _call(*) for each prompt synchronously.
        """
        gens = []
        for p in prompts:
            txt = self._call(p, stop=stop)
            # Build Generation object; if real Generation class exists, use it, else use fallback dataclass
            try:
                g = Generation(text=txt)
            except Exception:
                g = Generation(txt)
            gens.append([g])
        return LLMResult(generations=gens)

    @property
    def _llm_type(self) -> str:
        return "gemini_custom_llm"

    def _identifying_params(self) -> dict:
        return {
            "model_name": self.model_name,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "context_window": self.context_window
        }


# --- quick smoke test --------------------------------------------------------
if __name__ == "__main__":
    # basic smoke test (requires GEMINI_API_KEY in env or in .env)
    import sys
    try:
        llm = GeminiLLM()
        out = llm._call("Say hello and list 2 fruits.")
        print("OK — output:\n", out)
    except Exception as e:
        print("Error (run test):", e)
        sys.exit(1)
