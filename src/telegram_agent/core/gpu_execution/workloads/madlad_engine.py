"""4-bit MADLAD-400 inference with optional per-language PEFT LoRA adapters."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from telegram_agent.core.gpu_execution.workloads.madlad_languages import (
    UnknownLanguageError,
    normalize_to_madlad,
    parse_lora_languages,
    target_language_token,
)

logger = logging.getLogger(__name__)

ADAPTER_WEIGHTS_NAME = "adapter_model.safetensors"
ADAPTER_CONFIG_NAME = "adapter_config.json"
ADAPTER_META_NAME = "adapter_meta.json"
_HASH_CHUNK_SIZE = 1024 * 1024


def fix_madlad_embeddings(model: Any) -> Any:
    """Use MADLAD's real decoder embeddings as its untied input embeddings."""
    model.set_input_embeddings(model.decoder.embed_tokens)
    model.config.tie_word_embeddings = False
    return model


def load_peft_adapter(
    base_model: Any, adapter_path: str, *, adapter_name: str = "default"
) -> Any:
    from peft import PeftModel

    return PeftModel.from_pretrained(
        base_model, adapter_path, adapter_name=adapter_name
    )


def adapter_files_complete(adapter_dir: str | Path) -> bool:
    path = Path(adapter_dir)
    return path.is_dir() and all(
        (path / name).is_file()
        for name in (ADAPTER_CONFIG_NAME, ADAPTER_WEIGHTS_NAME)
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_adapter_meta(adapter_dir: str | Path) -> dict[str, Any] | None:
    meta_path = Path(adapter_dir) / ADAPTER_META_NAME
    if not meta_path.is_file():
        return None
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def configure_madlad_hf_home() -> None:
    madlad_hf_home = os.environ.get("MADLAD_HF_HOME", "").strip()
    if madlad_hf_home:
        os.environ["HF_HOME"] = madlad_hf_home


class MadladEngine:
    def __init__(
        self,
        *,
        model_id: str,
        adapter_dir: str,
        device: str,
        max_batch_size: int,
        default_beam_size: int,
        default_max_new_tokens: int,
        max_source_length: int,
        max_input_chars: int,
        gpu_concurrency: int = 1,
        hf_token: str | None = None,
        lora_languages: Sequence[str] | str | None = None,
    ) -> None:
        self.model_id = model_id
        self.adapter_dir = adapter_dir
        if isinstance(lora_languages, str) or lora_languages is None:
            self.lora_languages = parse_lora_languages(lora_languages)
        else:
            self.lora_languages = parse_lora_languages(
                ",".join(str(item) for item in lora_languages)
            )
        self.requested_device = device
        self.max_batch_size = max_batch_size
        self.default_beam_size = default_beam_size
        self.default_max_new_tokens = default_max_new_tokens
        self.max_source_length = max_source_length
        self.max_input_chars = max_input_chars
        self._hf_token = hf_token
        self._semaphore = threading.Semaphore(max(1, gpu_concurrency))

        self._model: Any = None
        self._base_model: Any = None
        self._tokenizer: Any = None
        self.device = "cpu"
        self.cuda_available = False
        self.ready = False
        self.adapter_loaded = False
        self.adapter_sha256: str | None = None
        self._loaded_adapters: dict[str, Path] = {}
        self._adapter_hashes: dict[str, str] = {}
        self._active_adapter: str | None = None

    def resolve_lang(self, code: str) -> str:
        lang = normalize_to_madlad(code)
        self._assert_known_target_token(target_language_token(lang))
        return lang

    def _assert_known_target_token(self, token: str) -> None:
        if self._tokenizer is None:
            return
        token_id = self._tokenizer.convert_tokens_to_ids(token)
        unk_id = getattr(self._tokenizer, "unk_token_id", None)
        if token_id is None or (unk_id is not None and token_id == unk_id):
            raise UnknownLanguageError(
                f"Target token {token!r} is not in the MADLAD tokenizer vocabulary"
            )

    def _language_adapter_dir(self, lang: str) -> Path:
        return Path(self.adapter_dir) / lang

    def _missing_adapter_files(self, adapter_path: Path) -> list[str]:
        return [
            name
            for name in (ADAPTER_CONFIG_NAME, ADAPTER_WEIGHTS_NAME)
            if not (adapter_path / name).is_file()
        ]

    def _complete_adapter_dir(self, lang: str) -> Path | None:
        adapter_path = self._language_adapter_dir(lang)
        if not adapter_path.is_dir() or self._missing_adapter_files(adapter_path):
            return None
        return adapter_path

    def _preferred_tokenizer_source(self) -> str:
        for lang in self.lora_languages:
            adapter_path = self._complete_adapter_dir(lang)
            if adapter_path is not None and (adapter_path / "tokenizer.json").is_file():
                return str(adapter_path)
        return self.model_id

    def load(self) -> None:
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, BitsAndBytesConfig

        configure_madlad_hf_home()
        self.cuda_available = torch.cuda.is_available()
        if self.requested_device == "auto":
            self.device = "cuda" if self.cuda_available else "cpu"
        elif self.requested_device == "cuda":
            if not self.cuda_available:
                raise RuntimeError("MADLAD_DEVICE=cuda but CUDA is unavailable")
            self.device = "cuda"
        else:
            self.device = "cpu"
        if self.device != "cuda":
            raise RuntimeError("4-bit MADLAD inference requires a CUDA GPU")

        tokenizer_source = self._preferred_tokenizer_source()
        logger.info("Loading MADLAD tokenizer from %s", tokenizer_source)
        self._tokenizer = AutoTokenizer.from_pretrained(
            tokenizer_source, token=self._hf_token
        )
        if self._tokenizer.pad_token_id is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token

        compute_dtype = (
            torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        )
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=compute_dtype,
        )
        logger.info(
            "Loading 4-bit MADLAD model_id=%s dtype=%s",
            self.model_id,
            compute_dtype,
        )
        base = AutoModelForSeq2SeqLM.from_pretrained(
            self.model_id,
            quantization_config=quantization_config,
            dtype=compute_dtype,
            device_map={"": 0},
            token=self._hf_token,
        )
        self._base_model = fix_madlad_embeddings(base)
        self._attach_available_adapters()
        self.ready = True
        loaded = ",".join(self._loaded_adapters) or "none"
        logger.info(
            "MADLAD ready model_id=%s loaded_adapters=%s sha256=%s",
            self.model_id,
            loaded,
            self.adapter_sha256,
        )

    def _register_adapter(self, lang: str, adapter_path: Path) -> None:
        self._loaded_adapters[lang] = adapter_path
        weights = adapter_path / ADAPTER_WEIGHTS_NAME
        self._adapter_hashes[lang] = sha256_file(weights)

    def _use_base_model(self) -> None:
        if self._base_model is None:
            raise RuntimeError("Base MADLAD model is not loaded")
        self._model = self._base_model
        self._model.eval()
        self._model.config.use_cache = True
        self._loaded_adapters = {}
        self._adapter_hashes = {}
        self._active_adapter = None
        self.adapter_loaded = False
        self.adapter_sha256 = None

    def _attach_available_adapters(self) -> None:
        if self._base_model is None:
            raise RuntimeError("Base MADLAD model is not loaded")

        complete: list[tuple[str, Path]] = []
        for lang in self.lora_languages:
            adapter_path = self._language_adapter_dir(lang)
            if not adapter_path.is_dir():
                logger.warning(
                    "MADLAD LoRA for %s not found at %s; using base model for that language",
                    lang,
                    adapter_path,
                )
                continue
            missing = self._missing_adapter_files(adapter_path)
            if missing:
                logger.warning(
                    "MADLAD LoRA for %s at %s is missing %s; using base model for that language",
                    lang,
                    adapter_path,
                    ", ".join(missing),
                )
                continue
            complete.append((lang, adapter_path))

        if not complete:
            self._use_base_model()
            return

        wrapped: Any = None
        self._loaded_adapters = {}
        self._adapter_hashes = {}
        for lang, adapter_path in complete:
            try:
                if wrapped is None:
                    wrapped = load_peft_adapter(
                        self._base_model, str(adapter_path), adapter_name=lang
                    )
                else:
                    wrapped.load_adapter(str(adapter_path), adapter_name=lang)
            except Exception:
                logger.exception(
                    "Failed to load MADLAD LoRA for %s from %s; skipping",
                    lang,
                    adapter_path,
                )
                continue
            self._register_adapter(lang, adapter_path)

        if wrapped is None or not self._loaded_adapters:
            self._use_base_model()
            return

        wrapped.eval()
        wrapped.config.use_cache = True
        self._model = wrapped
        self.adapter_loaded = True
        first_lang = next(iter(self._loaded_adapters))
        self._activate_adapter(first_lang)

    def _activate_adapter(self, lang: str) -> None:
        if lang in self._loaded_adapters:
            set_adapter = getattr(self._model, "set_adapter", None)
            enable = getattr(self._model, "enable_adapter_layers", None)
            if callable(set_adapter):
                set_adapter(lang)
            if callable(enable):
                enable()
            self._active_adapter = lang
            self.adapter_sha256 = self._adapter_hashes.get(lang)
            return
        disable = getattr(self._model, "disable_adapter_layers", None)
        if callable(disable):
            disable()
        self._active_adapter = None
        self.adapter_sha256 = None

    def reload_adapter(self) -> str | None:
        with self._semaphore:
            if self._base_model is None:
                raise RuntimeError("Base MADLAD model is not loaded")
            previous = self._model
            self._attach_available_adapters()
            if previous is not None and previous is not self._model:
                del previous
        loaded = ",".join(self._loaded_adapters) or "none"
        logger.info(
            "Reloaded MADLAD adapters=%s sha256=%s", loaded, self.adapter_sha256
        )
        return self.adapter_sha256

    def translate_batch(
        self,
        texts: list[str],
        *,
        target_lang: str,
        source_lang: str | None = None,
        beam_size: int | None = None,
        max_new_tokens: int | None = None,
    ) -> list[str]:
        del source_lang
        if not self.ready or self._model is None or self._tokenizer is None:
            raise RuntimeError("MADLAD engine is not ready")
        if not texts:
            raise ValueError("texts must not be empty")
        if len(texts) > self.max_batch_size:
            raise ValueError(
                f"Batch size {len(texts)} exceeds max_batch_size={self.max_batch_size}"
            )

        resolved_target = self.resolve_lang(target_lang)
        prefix = target_language_token(resolved_target)
        beam = beam_size or self.default_beam_size
        max_tokens = max_new_tokens or self.default_max_new_tokens
        non_empty_indexes: list[int] = []
        non_empty_texts: list[str] = []
        for index, text in enumerate(texts):
            if text is None:
                raise ValueError("texts must not contain null entries")
            if len(text) > self.max_input_chars:
                raise ValueError(
                    f"Text at index {index} exceeds max_input_chars={self.max_input_chars}"
                )
            if not text.strip():
                continue
            non_empty_indexes.append(index)
            non_empty_texts.append(text)

        results = [""] * len(texts)
        if not non_empty_texts:
            return results
        with self._semaphore:
            self._activate_adapter(resolved_target)
            translated = self._translate_non_empty(
                non_empty_texts,
                target_token=prefix,
                beam_size=beam,
                max_new_tokens=max_tokens,
            )
        if len(translated) != len(non_empty_texts):
            raise RuntimeError("MADLAD generator returned an invalid result count")
        for index, text in zip(non_empty_indexes, translated):
            results[index] = text
        return results

    def _translate_non_empty(
        self,
        texts: list[str],
        *,
        target_token: str,
        beam_size: int,
        max_new_tokens: int,
    ) -> list[str]:
        import torch

        prefixed = [f"{target_token} {text.strip()}" for text in texts]
        encoded = self._tokenizer(
            prefixed,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=self.max_source_length,
        )
        encoded = {key: value.to(self._model.device) for key, value in encoded.items()}
        with torch.inference_mode():
            generated = self._model.generate(
                **encoded,
                max_new_tokens=max_new_tokens,
                num_beams=beam_size,
                pad_token_id=self._tokenizer.pad_token_id,
            )
        decoded = self._tokenizer.batch_decode(generated, skip_special_tokens=True)
        return [text.strip() for text in decoded]
