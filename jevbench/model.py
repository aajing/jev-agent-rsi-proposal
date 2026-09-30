"""Pinned, local System-2 inference. No decision adapter or external inference."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
from .contract import ContractError

MODEL_REPO = "autotrust/JEV-27B-VL"
MODEL_REVISION = "3ea6d7a3a140d2d08e6a64174195967013168d5b"


def verify_model_files(path, lock_path=None):
    path = Path(path)
    lock_path = Path(lock_path) if lock_path else Path(__file__).resolve().parents[1] / "configs/model_lock.json"
    lock = json.loads(lock_path.read_text())
    if lock.get("repo") != MODEL_REPO or lock.get("revision") != MODEL_REVISION:
        raise ContractError("Invalid trusted model lock")
    expected = set(lock["files"])
    for file in path.rglob("*"):
        name = file.relative_to(path).as_posix()
        if name.startswith(".cache/") or file.is_dir() or name == "jevbench_model_pin.json":
            continue
        if name not in expected:
            raise ContractError("Unexpected file in frozen model directory")
    for name, info in lock["files"].items():
        file = path / name
        if not file.is_file() or file.stat().st_size != info["bytes"]:
            raise ContractError("Missing or altered model asset: " + name)
        sha = hashlib.sha256() if "sha256" in info else hashlib.sha1()
        if "sha256" not in info:
            sha.update(f"blob {info['bytes']}\0".encode())
        with file.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8*1024*1024), b""):
                sha.update(chunk)
        if sha.hexdigest() != (info["sha256"] if "sha256" in info else info["git_blob_sha1"]):
            raise ContractError("Model asset checksum mismatch: " + name)
    return {"verified_files": len(expected), "revision": MODEL_REVISION}


class TransformersBackend:
    def __init__(self, model_path):
        import torch
        from transformers import AutoProcessor, Qwen3_5ForConditionalGeneration
        if not torch.cuda.is_available():
            raise RuntimeError("Real baseline requires a CUDA GPU; a mock result is not accepted")
        path = Path(model_path)
        pin = json.loads((path / "jevbench_model_pin.json").read_text())
        if pin.get("repo") != MODEL_REPO or pin.get("revision") != MODEL_REVISION:
            raise ContractError("Wrong model snapshot")
        self.file_verification = verify_model_files(path)
        self.torch = torch
        self.processor = AutoProcessor.from_pretrained(path, local_files_only=True, trust_remote_code=False)
        self.model = Qwen3_5ForConditionalGeneration.from_pretrained(
            path, local_files_only=True, trust_remote_code=False,
            dtype=torch.bfloat16, device_map={"": "cuda:0"}, attn_implementation="sdpa")
        self.model.eval()
        torch.manual_seed(0)
        torch.cuda.manual_seed_all(0)
        self.model_path = str(path)
        self.calls = []

    def token_count(self, text):
        return len(self.processor.tokenizer.encode(text, add_special_tokens=False))

    def generate(self, request, *, max_output, meter):
        images = request["images"]
        if len(images) > 2:
            raise ContractError("Too many observations")
        content = [{"type": "image", "image": image} for image in images]
        content.append({"type": "text", "text": request["user"]})
        messages = [{"role": "system", "content": request["system"]}, {"role": "user", "content": content}]
        inputs = self.processor.apply_chat_template(messages, tokenize=True,
            add_generation_prompt=True, return_dict=True, return_tensors="pt", enable_thinking=False)
        grid = inputs.get("image_grid_thw")
        if grid is not None:
            merge = int(self.model.config.vision_config.spatial_merge_size)
            visual_counts = [int(row.prod().item()) // (merge * merge) for row in grid]
            if len(visual_counts) != len(images) or any(n > 1024 for n in visual_counts):
                raise ContractError("Native image token budget exceeded")
        elif images:
            raise ContractError("Processor returned no auditable image token grid")
        input_tokens = int(inputs["input_ids"].shape[-1])
        meter.begin(input_tokens, max_output)
        inputs = inputs.to("cuda:0")
        with self.torch.inference_mode():
            result = self.model.generate(**inputs, do_sample=False, max_new_tokens=max_output,
                use_cache=True, max_time=max(0.1, meter.limits["seconds"]-meter.summary()["seconds"]))
        generated = result[0, input_tokens:]
        count = int(generated.numel())
        meter.end(count)
        text = self.processor.tokenizer.decode(generated, skip_special_tokens=True)
        self.calls.append({"input_tokens": input_tokens, "output_tokens": count,
            "max_output": max_output, "image_tokens": visual_counts if grid is not None else []})
        return text

    def evidence(self, *, aggregate_only=False):
        return {"repo": MODEL_REPO, "revision": MODEL_REVISION, "mode": "System 2",
            "active_decision_adapter": False, "base": "unmodified Qwen3.8-27B",
            "dtype": "bfloat16", "attention": "sdpa", "thinking": False,
            "file_verification": self.file_verification,
            "device": self.torch.cuda.get_device_name(0),
            "peak_allocated_bytes": self.torch.cuda.max_memory_allocated(0),
            "peak_reserved_bytes": self.torch.cuda.max_memory_reserved(0),
            "call_count": len(self.calls),
            **({} if aggregate_only else {"calls": self.calls})}
