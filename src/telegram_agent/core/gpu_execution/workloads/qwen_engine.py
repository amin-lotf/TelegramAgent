"""Qwen3 Instruct structured generation. Imported only in the GPU child."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "Qwen/Qwen3-4B-Instruct-2507"
DEFAULT_DEVICE = "cuda"


class QwenEngineError(RuntimeError):
    """Raised when the local Qwen runtime cannot produce JSON."""


class QwenStructuredEngine:
    def __init__(
        self,
        *,
        model_id: str,
        device: str = DEFAULT_DEVICE,
        hf_token: str | None = None,
    ) -> None:
        self.model_id = model_id
        self.device = device.strip() or DEFAULT_DEVICE
        self.hf_token = hf_token
        self._model: Any = None
        self._tokenizer: Any = None
        self._outlines_model: Any = None

    def load(self) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        kwargs: dict[str, Any] = {}
        if self.hf_token:
            kwargs["token"] = self.hf_token
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_id, **kwargs)
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        model_kwargs: dict[str, Any] = dict(kwargs)
        if self.device in {"cuda", "auto"} and torch.cuda.is_available():
            model_kwargs["torch_dtype"] = dtype
            model_kwargs["device_map"] = "auto"
        self._model = AutoModelForCausalLM.from_pretrained(self.model_id, **model_kwargs)
        if self.device == "cpu":
            self._model = self._model.to("cpu")
        self._model.eval()
        logger.info("Loaded Qwen model %s device=%s", self.model_id, self.device)

    def close(self) -> None:
        self._outlines_model = None
        self._model = None
        self._tokenizer = None

    def generate_json(
        self,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any],
        *,
        max_new_tokens: int,
        temperature: float,
    ) -> tuple[dict[str, Any], dict[str, int]]:
        if self._model is None or self._tokenizer is None:
            raise QwenEngineError("Qwen model is not loaded")
        prompt = self._tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        if not isinstance(prompt, str) or not prompt.strip():
            raise QwenEngineError("Qwen chat template produced an empty prompt")
        raw_text, usage = self._generate_text(
            prompt,
            json_schema,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
        )
        parsed = parse_json_object(raw_text)
        return parsed, usage

    def _generate_text(
        self,
        prompt: str,
        json_schema: dict[str, Any],
        *,
        max_new_tokens: int,
        temperature: float,
    ) -> tuple[str, dict[str, int]]:
        try:
            text = self._generate_constrained(
                prompt,
                json_schema,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
            )
            usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
            return text, usage
        except Exception as exc:
            message = str(exc).lower()
            if "out of memory" in message or ("cuda" in message and "memory" in message):
                raise
            logger.warning("Constrained Qwen decoding unavailable: %s", exc)
        return self._generate_unconstrained(
            prompt,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
        )

    def _generate_constrained(
        self,
        prompt: str,
        json_schema: dict[str, Any],
        *,
        max_new_tokens: int,
        temperature: float,
    ) -> str:
        import outlines
        from outlines.types import JsonSchema

        if self._outlines_model is None:
            self._outlines_model = outlines.from_transformers(
                self._model, self._tokenizer
            )
        generator = outlines.Generator(
            self._outlines_model, JsonSchema(json.dumps(json_schema))
        )
        kwargs: dict[str, Any] = {"max_new_tokens": max_new_tokens}
        if temperature > 0:
            kwargs["temperature"] = temperature
        result = generator(prompt, **kwargs)
        if isinstance(result, list):
            result = result[0]
        return str(result)

    def _generate_unconstrained(
        self,
        prompt: str,
        *,
        max_new_tokens: int,
        temperature: float,
    ) -> tuple[str, dict[str, int]]:
        import torch

        assert self._model is not None
        assert self._tokenizer is not None
        inputs = self._tokenizer(prompt, return_tensors="pt")
        model_device = next(self._model.parameters()).device
        inputs = {key: value.to(model_device) for key, value in inputs.items()}
        input_tokens = int(inputs["input_ids"].shape[-1])
        generate_kwargs: dict[str, Any] = {
            "max_new_tokens": max_new_tokens,
            "do_sample": temperature > 0,
        }
        if temperature > 0:
            generate_kwargs["temperature"] = temperature
        with torch.inference_mode():
            output_ids = self._model.generate(**inputs, **generate_kwargs)
        generated = output_ids[0][input_tokens:]
        text = self._tokenizer.decode(generated, skip_special_tokens=True)
        output_tokens = int(generated.shape[-1])
        usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        return text, usage


def parse_json_object(text: str) -> dict[str, Any]:
    candidate = extract_json_text(text)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise QwenEngineError("Qwen output was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise QwenEngineError("Qwen output JSON must be an object")
    return payload


def extract_json_text(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1]
        if stripped.endswith("```"):
            stripped = stripped[: -len("```")].rstrip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise QwenEngineError("Qwen output did not contain a JSON object")
    return stripped[start : end + 1]
