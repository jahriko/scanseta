import asyncio
import importlib.util
import os
import unittest
from unittest.mock import patch

import torch


def _deps_available() -> bool:
    required = ["fastapi", "torch", "transformers", "peft", "PIL"]
    return all(importlib.util.find_spec(name) is not None for name in required)


class _FakeModel:
    def __init__(self, hf_device_map):
        self.hf_device_map = hf_device_map
        self._param = torch.zeros(1, dtype=torch.float16)
        self.to_calls = []
        self.eval_called = False

    def to(self, device):
        self.to_calls.append(device)
        return self

    def eval(self):
        self.eval_called = True
        return self

    def parameters(self):
        return iter([self._param])


class _StubBitsAndBytesConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


@unittest.skipUnless(_deps_available(), "Model loading tests require backend runtime dependencies")
class TestModelLoadingPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main as backend_main

        if backend_main.AutoModelForVision2Seq is None:
            raise unittest.SkipTest("Transformers vision model class is unavailable")

        cls.backend_main = backend_main

    def test_loader_defaults_to_single_gpu_when_cuda_available(self):
        model = _FakeModel({"language_model": "cuda:0", "lm_head": "cuda:0"})
        with patch.object(self.backend_main.os, "makedirs", return_value=None):
            with patch.object(self.backend_main.torch.cuda, "is_available", return_value=True):
                with patch.dict(os.environ, {"HF_LOAD_POLICY": "fail_fast", "HF_ENABLE_4BIT": "0"}, clear=False):
                    os.environ.pop("HF_DEVICE_MAP", None)
                    with patch.object(self.backend_main.AutoProcessor, "from_pretrained", return_value=object()):
                        with patch.object(self.backend_main.PeftModel, "from_pretrained", side_effect=lambda m, *_a, **_k: m):
                            with patch.object(self.backend_main.AutoModelForVision2Seq, "from_pretrained", return_value=model) as mock_loader:
                                self.backend_main.load_qwen_vl_with_lora("base/model", "adapter/repo")

        self.assertEqual(mock_loader.call_count, 1)
        self.assertEqual(mock_loader.call_args.kwargs["device_map"], {"": "cuda:0"})

    def test_fail_fast_no_auto_or_cpu_fallback(self):
        with patch.object(self.backend_main.os, "makedirs", return_value=None):
            with patch.object(self.backend_main.torch.cuda, "is_available", return_value=True):
                with patch.dict(os.environ, {"HF_LOAD_POLICY": "fail_fast", "HF_ENABLE_4BIT": "0"}, clear=False):
                    os.environ.pop("HF_DEVICE_MAP", None)
                    with patch.object(self.backend_main.AutoProcessor, "from_pretrained", return_value=object()):
                        with patch.object(
                            self.backend_main.AutoModelForVision2Seq,
                            "from_pretrained",
                            side_effect=RuntimeError("CUDA out of memory"),
                        ) as mock_loader:
                            with self.assertRaises(RuntimeError):
                                self.backend_main.load_qwen_vl_with_lora("base/model", "adapter/repo")

        self.assertEqual(mock_loader.call_count, 1)
        self.assertEqual(mock_loader.call_args.kwargs["device_map"], {"": "cuda:0"})

    def test_language_module_offloaded_raises_under_fail_fast(self):
        model = _FakeModel({"language_model": "cpu", "lm_head": "cpu"})
        with patch.object(self.backend_main.os, "makedirs", return_value=None):
            with patch.object(self.backend_main.torch.cuda, "is_available", return_value=True):
                with patch.dict(os.environ, {"HF_LOAD_POLICY": "fail_fast", "HF_ENABLE_4BIT": "0"}, clear=False):
                    os.environ.pop("HF_DEVICE_MAP", None)
                    with patch.object(self.backend_main.AutoProcessor, "from_pretrained", return_value=object()):
                        with patch.object(self.backend_main.AutoModelForVision2Seq, "from_pretrained", return_value=model):
                            with patch.object(self.backend_main.PeftModel, "from_pretrained", side_effect=lambda m, *_a, **_k: m):
                                with self.assertRaisesRegex(RuntimeError, "Language model is not fully on GPU"):
                                    self.backend_main.load_qwen_vl_with_lora("base/model", "adapter/repo")

    def test_quantization_import_error_retries_without_4bit_same_device_map(self):
        model = _FakeModel({"language_model": "cuda:0", "lm_head": "cuda:0"})
        with patch.object(self.backend_main.os, "makedirs", return_value=None):
            with patch.object(self.backend_main.torch.cuda, "is_available", return_value=True):
                with patch.dict(os.environ, {"HF_LOAD_POLICY": "fail_fast", "HF_ENABLE_4BIT": "1"}, clear=False):
                    os.environ.pop("HF_DEVICE_MAP", None)
                    with patch.object(self.backend_main, "BitsAndBytesConfig", _StubBitsAndBytesConfig):
                        with patch.object(self.backend_main.AutoProcessor, "from_pretrained", return_value=object()):
                            with patch.object(self.backend_main.PeftModel, "from_pretrained", side_effect=lambda m, *_a, **_k: m):
                                with patch.object(
                                    self.backend_main.AutoModelForVision2Seq,
                                    "from_pretrained",
                                    side_effect=[ImportError("No module named bitsandbytes"), model],
                                ) as mock_loader:
                                    self.backend_main.load_qwen_vl_with_lora("base/model", "adapter/repo")

        self.assertEqual(mock_loader.call_count, 2)
        first_kwargs = mock_loader.call_args_list[0].kwargs
        second_kwargs = mock_loader.call_args_list[1].kwargs
        self.assertEqual(first_kwargs["device_map"], {"": "cuda:0"})
        self.assertEqual(second_kwargs["device_map"], {"": "cuda:0"})
        self.assertIn("quantization_config", first_kwargs)
        self.assertNotIn("quantization_config", second_kwargs)

    def test_processor_load_retries_when_hf_client_was_closed(self):
        model = _FakeModel({"language_model": "cpu", "lm_head": "cpu"})
        with patch.object(self.backend_main.os, "makedirs", return_value=None):
            with patch.object(self.backend_main.torch.cuda, "is_available", return_value=False):
                with patch.dict(os.environ, {"HF_LOAD_POLICY": "fallback_auto_cpu", "HF_ENABLE_4BIT": "0"}, clear=False):
                    with patch.object(
                        self.backend_main.AutoProcessor,
                        "from_pretrained",
                        side_effect=[
                            RuntimeError("Cannot send a request, as the client has been closed."),
                            object(),
                        ],
                    ) as mock_processor_loader:
                        with patch.object(self.backend_main.PeftModel, "from_pretrained", side_effect=lambda m, *_a, **_k: m):
                            with patch.object(self.backend_main.AutoModelForVision2Seq, "from_pretrained", return_value=model):
                                self.backend_main.load_qwen_vl_with_lora("base/model", "adapter/repo")

        self.assertEqual(mock_processor_loader.call_count, 2)

    def test_get_status_includes_new_fields(self):
        with patch.object(self.backend_main.torch.cuda, "is_available", return_value=False):
            config = self.backend_main.ModelConfig()
            config.model = _FakeModel({"language_model": "cuda:0", "lm_head": "cuda:0"})
            config.device_map_mode = "single_gpu"
            config.language_model_on_gpu = True
            config.degraded_mode = False
            config.last_load_error = None
            status = config.get_status()

        self.assertIn("load_policy", status)
        self.assertIn("device_map_mode", status)
        self.assertIn("language_model_on_gpu", status)
        self.assertIn("degraded_mode", status)
        self.assertIn("last_load_error", status)

    def test_model_status_reports_not_ready_after_load_failure(self):
        class _StubModelConfig:
            model = None

            def get_status(self):
                return {
                    "model_loaded": False,
                    "degraded_mode": False,
                    "last_load_error": "load failed",
                }

        with patch.object(self.backend_main, "model_config", _StubModelConfig()):
            payload = asyncio.run(self.backend_main.model_status())

        self.assertFalse(payload["model_loaded"])
        self.assertEqual(payload["last_load_error"], "load failed")

    def test_health_model_ready_contract(self):
        class _StubModelConfig:
            def __init__(self):
                self.model = None
                self.device = "cuda"
                self.degraded_mode = False

            def is_ready(self):
                return self.model is not None and not self.degraded_mode

        stub = _StubModelConfig()
        with patch.object(self.backend_main, "model_config", stub):
            with patch.object(self.backend_main.torch.cuda, "is_available", return_value=True):
                healthy_none = asyncio.run(self.backend_main.health_check())
                stub.model = object()
                stub.degraded_mode = False
                healthy_loaded = asyncio.run(self.backend_main.health_check())
                stub.degraded_mode = True
                healthy_degraded = asyncio.run(self.backend_main.health_check())

        self.assertFalse(healthy_none["model_ready"])
        self.assertTrue(healthy_loaded["model_ready"])
        self.assertFalse(healthy_degraded["model_ready"])


if __name__ == "__main__":
    unittest.main()
