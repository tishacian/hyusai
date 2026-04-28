import asyncio
import base64
import io
import os
import re
import types
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import torch
from PIL import Image
from transformers import (
    AutoModelForCausalLM,
    AutoModelForVision2Seq,
    AutoProcessor,
    Qwen2_5_VLForConditionalGeneration,
)
from vllm import LLM, SamplingParams

from src.globalvariables import VLMConfig as _VLMGlobals


def _vlm_config() -> types.SimpleNamespace:
    V = _VLMGlobals
    return types.SimpleNamespace(
        enable_vlm=V.ENABLE_VLM.value,
        vlm_model=V.VLM_MODEL.value,
        vlm_workers=V.VLM_WORKERS.value,
        max_workers=V.MAX_WORKERS.value,
        skip_large_images=V.SKIP_LARGE_IMAGES.value,
        max_model_len=V.MAX_MODEL_LEN.value,
        gpu_memory_utilization=V.GPU_MEMORY_UTILIZATION.value,
        temperature=V.TEMPERATURE.value,
        max_tokens=V.MAX_TOKENS.value,
        top_p=V.TOP_P.value,
        frequency_penalty=V.FREQUENCY_PENALTY.value,
        presence_penalty=V.PRESENCE_PENALTY.value,
        repetition_penalty=V.REPETITION_PENALTY.value,
        max_image_size=V.MAX_IMAGE_SIZE.value,
        min_image_size=V.MIN_IMAGE_SIZE.value,
        max_tokens_limit=V.MAX_TOKENS_LIMIT.value,
        jpeg_quality_levels=V.JPEG_QUALITY_LEVELS.value,
        device=V.DEVICE.value,
        use_flash_attention=V.USE_FLASH_ATTENTION.value,
        torch_dtype=V.TORCH_DTYPE.value,
    )


@dataclass
class VLMResult:
    extracted_text: str
    description: str
    confidence: float
    model_used: str
    processing_time: float = 0.0


class BaseVLM(ABC):
    def __init__(self, model_name: str, device: str = "auto") -> None:
        """Initialize the base VLM class.

        Parameters
        ----------
        model_name : str
            Name of the model to load.
        device : str, optional
            Device to use for inference, by default "auto".
        """
        self.model_name = model_name
        self.device = self._get_best_device() if device == "auto" else device
        self.model = None
        self.processor = None
        self._load_model()

    @abstractmethod
    def _load_model(self) -> None:
        pass

    @abstractmethod
    async def _generate_response(self, image: Image.Image, prompt: str) -> str:
        """Generate response from the model.

        Parameters
        ----------
        image : Image.Image
            Input image.
        prompt : str
            Text prompt.

        Returns
        -------
        str
            Model response.
        """
        pass

    async def analyze_image(self, image_path: str) -> VLMResult:
        """Analyze an image and return extracted text and description.

        Parameters
        ----------
        image_path : str
            Path to the image file to analyze.

        Returns
        -------
        VLMResult
            Analysis result containing extracted text and description.
        """
        start_time = asyncio.get_event_loop().time()

        try:
            image = self._load_image(image_path)
            combined_prompt = self._get_standard_prompt()

            full_response = await self._generate_response(image, combined_prompt)
            extracted_text, description = ResponseParser.parse_combined_response(
                full_response
            )

            processing_time = asyncio.get_event_loop().time() - start_time

            return VLMResult(
                extracted_text=extracted_text,
                description=description,
                confidence=self._get_confidence(),
                model_used=self._get_model_name(),
                processing_time=processing_time,
            )

        except Exception as e:
            processing_time = asyncio.get_event_loop().time() - start_time
            return VLMResult(
                extracted_text="",
                description=f"Error analyzing image: {str(e)}",
                confidence=0.0,
                model_used=self._get_model_name(),
                processing_time=processing_time,
            )

    def _get_standard_prompt(self) -> str:
        """Get the standard prompt for all VLM models."""
        return (
            "You are an advanced AI agent specialized in image analysis "
            "and OCR. Analyze this image and provide results in exactly "
            "this format:\n\n"
            "OCR TEXT: [Perform OCR now and extract any visible text, "
            "numbers, symbols, or characters. If no text is visible, "
            "write 'No visible text found']\n\n"
            "IMAGE DESCRIPTION: [Describe the image content including "
            "objects, people, scenes, colors, layout, and visual "
            "elements]\n\n"
            "Important: Actually perform OCR and extract real text. "
            "Do not repeat instructions. Only return the OCR TEXT and "
            "IMAGE DESCRIPTION sections with actual results."
        )

    def _get_confidence(self) -> float:
        """Get confidence score for the model."""
        return 0.85

    def _get_model_name(self) -> str:
        """Get model name for identification."""
        return self.model_name

    def _get_best_device(self) -> str:
        """Get the best available device for inference.

        Returns
        -------
        str
            Device identifier (cuda, mps, or cpu).
        """
        if torch.cuda.is_available():
            return "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        else:
            return "cpu"

    def _load_image(self, image_path: str) -> Image.Image:
        """Load and validate image.

        Parameters
        ----------
        image_path : str
            Path to the image file.

        Returns
        -------
        Image.Image
            Loaded PIL image object.

        Raises
        ------
        FileNotFoundError
            If the image file doesn't exist.
        ValueError
            If the image cannot be loaded.
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")

        try:
            image = Image.open(image_path)
            if image.mode != "RGB":
                image = image.convert("RGB")
            return image
        except Exception as e:
            raise ValueError(f"Failed to load image {image_path}: {e}")

    def _clean_prompt_echo(self, text: str, prompt: str) -> str:
        """Remove prompt echo from VLM output.

        Parameters
        ----------
        text : str
            Text to clean.
        prompt : str
            Prompt to remove from text.

        Returns
        -------
        str
            Cleaned text without prompt echoes.
        """
        if not text or not prompt:
            return text

        patterns = [
            rf"^{re.escape(prompt)}\s*:?\s*",
            rf"^{re.escape(prompt.lower())}\s*:?\s*",
            rf"^{re.escape(prompt.upper())}\s*:?\s*",
            r"^extract all visible text from this image\s*:?\s*",
            r"^describe this image in detail\s*:?\s*",
            r"^please extract all visible text from this image\s*:?\s*",
            r"^please describe this image in detail\s*:?\s*",
        ]

        cleaned_text = text
        for pattern in patterns:
            cleaned_text = re.sub(pattern, "", cleaned_text, flags=re.IGNORECASE)

        return cleaned_text.strip()


class ResponseParser:
    @staticmethod
    def parse_combined_response(response: str) -> tuple[str, str]:
        """Parse combined response to extract text and description.

        Parameters
        ----------
        response : str
            Raw response from VLM model.

        Returns
        -------
        tuple[str, str]
            Tuple of (extracted_text, description).
        """
        response = ResponseParser._remove_duplicates(response)
        response = re.sub(r"^Assistant:\s*", "", response, flags=re.IGNORECASE)

        prompt_patterns_to_remove = [
            r"\[Perform high-quality OCR.*?\]",
            r"\[extract all visible text.*?\]",
            r"\[describe the image content.*?\]",
            r"\[Provide a detailed.*?\]",
            r"Important: Only return.*?explanations\.",
            r"Please ensure your OCR.*?detailed\.",
            r"You are an advanced AI agent.*?format:",
            r"Analyze this image and provide results.*?format:",
            r"Your task is to analyze.*?format:",
        ]

        for pattern in prompt_patterns_to_remove:
            response = re.sub(pattern, "", response, flags=re.DOTALL | re.IGNORECASE)

        text_match = None
        desc_match = None

        text_match = re.search(
            r"OCR TEXT:\s*(.*?)(?=IMAGE DESCRIPTION:|$)",
            response,
            re.DOTALL | re.IGNORECASE,
        )
        desc_match = re.search(
            r"IMAGE DESCRIPTION:\s*(.*?)$", response, re.DOTALL | re.IGNORECASE
        )

        if not text_match or not desc_match:
            text_match = re.search(
                r"TEXT:\s*(.*?)(?=DESCRIPTION:|$)",
                response,
                re.DOTALL | re.IGNORECASE,
            )
            desc_match = re.search(
                r"DESCRIPTION:\s*(.*?)$", response, re.DOTALL | re.IGNORECASE
            )

        if not text_match or not desc_match:
            text_indicators = [
                r"text found[:\s]*([^.]*)",
                r"extracted text[:\s]*([^.]*)",
                r"visible text[:\s]*([^.]*)",
                r"text in image[:\s]*([^.]*)",
                r"ocr text[:\s]*([^.]*)",
            ]

            for pattern in text_indicators:
                text_match = re.search(pattern, response, re.IGNORECASE)
                if text_match:
                    break

            if text_match:
                text_start = text_match.end()
                description = response[text_start:].strip()
                description = re.sub(r"^[:\s]*", "", description)
                extracted_text = text_match.group(1).strip()
            else:
                extracted_text = ""
                description = response.strip()
        else:
            extracted_text = text_match.group(1).strip()
            description = desc_match.group(1).strip()

        extracted_text = ResponseParser._clean_prompt_echo(
            extracted_text, "Extract all visible text"
        )

        placeholder_patterns = [
            r"\[.*?\]",
            r"extract all visible text",
            r"numbers, symbols, and characters",
            r"If no text is visible, write",
            r"Perform high-quality OCR",
            r"Perform OCR now and extract",
            r"Actually perform OCR",
            r"Do not repeat instructions",
            r"Only return the OCR TEXT",
            r"Important:.*?results\.",
        ]

        for pattern in placeholder_patterns:
            extracted_text = re.sub(
                pattern, "", extracted_text, flags=re.IGNORECASE | re.DOTALL
            )

        extracted_text = extracted_text.strip()
        description = ResponseParser._clean_prompt_echo(
            description, "Describe this image"
        )

        instruction_patterns = [
            r"Important:.*?Assistant:",
            r"Actually perform OCR.*?Assistant:",
            r"Do not repeat instructions.*?Assistant:",
            r"Only return the OCR TEXT.*?Assistant:",
            r"Important:.*?results\.",
            r"Actually perform OCR.*?results\.",
            r"Do not repeat instructions.*?results\.",
            r"Only return the OCR TEXT.*?results\.",
        ]

        for pattern in instruction_patterns:
            description = re.sub(
                pattern, "", description, flags=re.IGNORECASE | re.DOTALL
            )
        description = re.sub(r"^Assistant:\s*", "", description, flags=re.IGNORECASE)

        desc_placeholder_patterns = [
            r"\[description\]",
            r"\[image description\]",
            r"describe the image content",
            r"including objects, people, scenes",
            r"Provide a detailed",
            r"accurate description",
            r"visual elements",
            r"Be specific and comprehensive",
        ]

        for pattern in desc_placeholder_patterns:
            description = re.sub(pattern, "", description, flags=re.IGNORECASE)

        description = description.strip()
        description = re.sub(
            r"^(The|This|Here|In this image|This image shows?)\s+",
            "",
            description,
            flags=re.IGNORECASE,
        )
        description = ResponseParser._format_markdown_content(description)
        extracted_text = ResponseParser._remove_duplicates(extracted_text)
        description = ResponseParser._remove_duplicates(description)
        if not extracted_text or extracted_text.lower() in [
            "[text found]",
            "[extracted text]",
            "[ocr text]",
            "none",
            "no text",
            "no visible text found",
            "extract all visible text",
            "numbers, symbols, and characters",
            "",
        ]:
            extracted_text = ""

        return extracted_text, description

    @staticmethod
    def _format_markdown_content(text: str) -> str:
        """Format markdown content to be properly structured.

        Parameters
        ----------
        text : str
            Text to format.

        Returns
        -------
        str
            Formatted markdown content.
        """
        if not text:
            return text

        lines = text.split("\n")
        formatted_lines = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if re.match(r"^\d+\.\s*\*\*", line):
                formatted_lines.append(line)
            elif re.match(r"^\*\*.*\*\*$", line):
                formatted_lines.append(line)
            else:
                formatted_lines.append(line)

        return "\n".join(formatted_lines)

    @staticmethod
    def _clean_prompt_echo(text: str, prompt: str) -> str:
        """Remove prompt echo from VLM output.

        Parameters
        ----------
        text : str
            Text to clean.
        prompt : str
            Prompt to remove from text.

        Returns
        -------
        str
            Cleaned text without prompt echoes.
        """
        if not text or not prompt:
            return text

        patterns = [
            rf"^{re.escape(prompt)}\s*:?\s*",
            rf"^{re.escape(prompt.lower())}\s*:?\s*",
            rf"^{re.escape(prompt.upper())}\s*:?\s*",
            r"^extract all visible text from this image\s*:?\s*",
            r"^describe this image in detail\s*:?\s*",
            r"^please extract all visible text from this image\s*:?\s*",
            r"^please describe this image in detail\s*:?\s*",
        ]

        cleaned_text = text
        for pattern in patterns:
            cleaned_text = re.sub(pattern, "", cleaned_text, flags=re.IGNORECASE)

        return cleaned_text.strip()

    @staticmethod
    def _remove_duplicates(text: str) -> str:
        """Remove duplicate sentences and repetitive patterns.

        Parameters
        ----------
        text : str
            Text to clean.

        Returns
        -------
        str
            Text with duplicates removed.
        """
        if not text:
            return text

        sentences = re.split(r"[.!?]+", text)
        sentences = [s.strip() for s in sentences if s.strip()]

        seen = set()
        unique_sentences = []
        for sentence in sentences:
            normalized = re.sub(r"\s+", " ", sentence.lower().strip())
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique_sentences.append(sentence)

        result = ". ".join(unique_sentences)
        if result and not result.endswith("."):
            result += "."

        patterns_to_remove = [
            r"(###\s*[A-Za-z\s]+:?\s*)+",
            r"(Analysis:\s*)+",
            r"(Description:\s*)+",
            r"(Image Description:\s*)+",
        ]

        for pattern in patterns_to_remove:
            result = re.sub(pattern, "", result)

        return result.strip()


class BaseVLLMVLM(BaseVLM):
    def __init__(
        self,
        model_name: str,
        device: str = None,
        max_model_len: int = None,
        gpu_memory_utilization: float = None,
    ):
        """Initialize vLLM-based VLM.

        Parameters
        ----------
        model_name : str
            Model name.
        device : str, optional
            Device. The default is None.
        max_model_len : int, optional
            Maximum model length. The default is None.
        gpu_memory_utilization : float, optional
            GPU memory utilization. The default is None.
        """
        config = _vlm_config()
        if device is None:
            device = config.device
        if max_model_len is None:
            max_model_len = config.max_model_len
        if gpu_memory_utilization is None:
            gpu_memory_utilization = config.gpu_memory_utilization

        self.max_model_len = max_model_len
        self.gpu_memory_utilization = gpu_memory_utilization
        super().__init__(model_name, device)

    def _load_model(self):
        try:
            config = _vlm_config()
            self.llm = LLM(
                model=self.model_name,
                trust_remote_code=True,
                max_model_len=self.max_model_len,
                gpu_memory_utilization=self.gpu_memory_utilization,
                enforce_eager=True,
                max_num_batched_tokens=8192,
                max_num_seqs=256,
            )

            self.sampling_params = SamplingParams(
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                top_p=config.top_p,
                frequency_penalty=config.frequency_penalty,
                presence_penalty=config.presence_penalty,
                repetition_penalty=config.repetition_penalty,
                stop=["###", "TEXT:", "DESCRIPTION:", "\n\n\n"],
            )

        except Exception:
            raise

    async def _generate_response(self, image: Image.Image, prompt: str) -> str:
        """Generate response using vLLM.

        Parameters
        ----------
        image : Image.Image
            Image to generate response for.
        prompt : str
            Prompt to generate response for.

        Returns
        -------
        str
            Generated response.
        """
        try:
            prepared_prompt = self._prepare_vllm_prompt(image, prompt)
        except ValueError:
            return "Image too large for VLM analysis - skipped"

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            outputs = await loop.run_in_executor(
                executor,
                lambda: self.llm.generate([prepared_prompt], self.sampling_params),
            )

        return outputs[0].outputs[0].text.strip()

    def _prepare_vllm_prompt(self, image: Image.Image, prompt: str) -> str:
        """Prepare prompt for vLLM inference with image optimization.

        Parameters
        ----------
        image : Image.Image
            Image to prepare.
        prompt : str
            Prompt to prepare.

        Returns
        -------
        str
            Prepared prompt.
        """
        config = _vlm_config()
        max_size = config.max_image_size
        if max(image.size) > max_size:
            ratio = max_size / max(image.size)
            new_size = tuple(int(dim * ratio) for dim in image.size)
            image = image.resize(new_size, Image.Resampling.LANCZOS)

        # --
        buffer = io.BytesIO()
        quality_settings = config.jpeg_quality_levels

        for quality in quality_settings:
            buffer.seek(0)
            buffer.truncate(0)

            # -- using low quality JPEG to reduce img size
            image.save(buffer, format="JPEG", quality=quality, optimize=True)
            img_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
            # -- estimate token count (1 token ≈ 4 chars)
            estimated_tokens = len(img_base64) // 4
            if estimated_tokens < config.max_tokens_limit:
                break

        if estimated_tokens >= config.max_tokens_limit:
            # -- resize to tiny image
            max_size = config.min_image_size
            ratio = max_size / max(image.size)
            new_size = tuple(int(dim * ratio) for dim in image.size)
            image = image.resize(new_size, Image.Resampling.LANCZOS)

            buffer.seek(0)
            buffer.truncate(0)
            image.save(buffer, format="JPEG", quality=5, optimize=True)
            img_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
            estimated_tokens = len(img_base64) // 4
            if estimated_tokens >= config.max_tokens_limit:
                raise ValueError(
                    f"Image too large even after optimization: "
                    f"{estimated_tokens} tokens "
                    f"(limit: {config.max_tokens_limit})"
                )

        return f"<image>{img_base64}</image>\n{prompt}"

    def _get_model_name(self) -> str:
        """Get model name for vLLM models."""
        return f"vLLM-{self.model_name}"


class VLLMSmolVLM(BaseVLLMVLM):
    def __init__(
        self,
        model_name: str = "HuggingFaceTB/SmolVLM-500M-Instruct",
        device: str = "auto",
    ):
        """Init

        Parameters
        ----------
        model_name : str, optional
            model name. The default is "HuggingFaceTB/SmolVLM-500M-Instruct".
        device : str, optional
            device. The default is "auto".

        Returns
        -------
        None.
        """
        super().__init__(model_name, device)


class VLLMMoondreamVLM(BaseVLLMVLM):
    def __init__(self, model_name: str = "vikhyatk/moondream2", device: str = "auto"):
        """init
        Parameters
        ----------
        model_name : str, optional
            model name. The default is "vikhyatk/moondream2".
        device : str, optional
            device. The default is "auto".

        Returns
        -------
        None.
        """
        super().__init__(model_name, device)

    def _load_model(self):
        try:
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                revision="2025-06-21",
                trust_remote_code=True,
                device_map={"": self.device},
            )
        except Exception:
            raise

    async def _generate_response(self, image: Image.Image, prompt: str) -> str:
        """Generate response using Moondream model.

        Parameters
        ----------
        image : Image.Image
            Image to generate response for.
        prompt : str
            Prompt to generate response for.

        Returns
        -------
        str
            Generated response.
        """
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            result = await loop.run_in_executor(
                executor,
                lambda: self.model.answer_question(image, prompt),
            )

        return result if isinstance(result, str) else str(result)

    def _get_model_name(self) -> str:
        """Get model name for Moondream.

        Returns
        -------
        str
            Model name.
        """
        return "Moondream (Original)"

    def _get_confidence(self) -> float:
        """Get confidence score for Moondream.

        Returns
        -------
        float
            Confidence score.
        """
        return 0.88


class VLLMQwenVLM(BaseVLLMVLM):
    def __init__(
        self,
        model_name: str = "Qwen/Qwen2.5-VL-3B-Instruct",
        device: str = "auto",
    ):
        """init
        Parameters
        ----------
        model_name : str, optional
            model name. The default is "Qwen/Qwen2.5-VL-3B-Instruct".
        device : str, optional
            device. The default is "auto".

        Returns
        -------
        None.
        """
        super().__init__(model_name, device)


class SmolVLM(BaseVLM):
    def __init__(
        self,
        model_name: str = "HuggingFaceTB/SmolVLM-500M-Instruct",
        device: str = None,
    ):
        """init
        Parameters
        ----------
        model_name : str, optional
            model name. The default is "HuggingFaceTB/SmolVLM-500M-Instruct".
        device : str, optional
            device. The default is "auto".

        Returns
        -------
        None.
        """
        config = _vlm_config()
        if device is None:
            device = config.device

        super().__init__(model_name, device)

    def _load_model(self):
        try:
            config = _vlm_config()
            attn_impl = (
                "flash_attention_2"
                if (self.device == "cuda" and config.use_flash_attention)
                else "eager"
            )

            self.processor = AutoProcessor.from_pretrained(self.model_name)
            self.model = AutoModelForVision2Seq.from_pretrained(
                self.model_name,
                torch_dtype=config.torch_dtype,
                _attn_implementation=attn_impl,
            ).to(self.device)

        except Exception:
            raise

    async def _generate_response(self, image: Image.Image, prompt: str) -> str:
        """Generate response using SmolVLM.

        Parameters
        ----------
        image : Image.Image
            Image to generate response for.
        prompt : str
            Prompt to generate response for.

        Returns
        -------
        str
            Generated response.
        """
        config = _vlm_config()

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image"},
                    {"type": "text", "text": prompt},
                ],
            },
        ]

        prompt_text = self.processor.apply_chat_template(
            messages, add_generation_prompt=True
        )
        inputs = self.processor(
            text=prompt_text,
            images=[image],
            return_tensors="pt",
            truncation=True,
        )
        inputs = inputs.to(self.device)

        with torch.no_grad():
            generated_ids = self.model.generate(
                **inputs,
                max_new_tokens=config.max_tokens,
                do_sample=False,
                repetition_penalty=config.repetition_penalty,
                no_repeat_ngram_size=3,
            )
            generated_texts = self.processor.batch_decode(
                generated_ids, skip_special_tokens=True
            )

        return generated_texts[0]

    def _get_model_name(self) -> str:
        """Get model name for SmolVLM."""
        return f"SmolVLM ({self.model_name})"


class MoondreamVLM(BaseVLM):
    def __init__(self, model_name: str = "vikhyatk/moondream2", device: str = "auto"):
        """init
        Parameters
        ----------
        model_name : str, optional
            model name. The default is "vikhyatk/moondream2".
        device : str, optional
            device. The default is "auto".

        Returns
        -------
        None.
        """
        super().__init__(model_name, device)

    def _load_model(self):
        try:
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                revision="2025-06-21",
                trust_remote_code=True,
                device_map={"": self.device},
            )
        except Exception:
            raise

    async def _generate_response(self, image: Image.Image, prompt: str) -> str:
        """Generate response using Moondream.

        Parameters
        ----------
        image : Image.Image
            Image to generate response for.
        prompt : str
            Prompt to generate response for.

        Returns
        -------
        str
            Generated response.
        """
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            result = await loop.run_in_executor(
                executor,
                lambda: self.model.answer_question(image, prompt),
            )

        return result if isinstance(result, str) else str(result)

    def _get_model_name(self) -> str:
        """Get model name for Moondream.

        Returns
        -------
        str
            Model name.
        """
        return "Moondream"

    def _get_confidence(self) -> float:
        """Get confidence score for Moondream.

        Returns
        -------
        float
            Confidence score.
        """
        return 0.88


class QwenVLM(BaseVLM):
    def __init__(
        self,
        model_name: str = "Qwen/Qwen2.5-VL-3B-Instruct",
        device: str = "auto",
    ):
        """init
        Parameters
        ----------
        model_name : str, optional
            model name. The default is "Qwen/Qwen2.5-VL-3B-Instruct".
        device : str, optional
            device. The default is "auto".

        Returns
        -------
        None.
        """
        super().__init__(model_name, device)

    def _load_model(self):
        try:
            self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                self.model_name, torch_dtype="auto", device_map="auto"
            )

            self.processor = AutoProcessor.from_pretrained(self.model_name)

        except Exception:
            raise

    async def _generate_response(self, image: Image.Image, prompt: str) -> str:
        """Generate response using Qwen."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.processor(
            text=[text],
            images=[image],
            padding=True,
            return_tensors="pt",
        )
        inputs = inputs.to(self.device)
        config = _vlm_config()

        with torch.no_grad():
            generated_ids = self.model.generate(
                **inputs,
                max_new_tokens=config.max_tokens,
                do_sample=False,
                repetition_penalty=config.repetition_penalty,
                no_repeat_ngram_size=3,
            )
            generated_ids_trimmed = [
                out_ids[len(in_ids) :]
                for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            output_text = self.processor.batch_decode(
                generated_ids_trimmed,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )

        return output_text[0]

    def _get_model_name(self) -> str:
        """Get model name for Qwen.

        Returns
        -------
        str
            Model name.
        """
        return "Qwen 2.5 VL"

    def _get_confidence(self) -> float:
        """Get confidence score for Qwen.

        Returns
        -------
        float
            Confidence score.
        """
        return 0.90


class VLMLoader:
    _models = {
        # -- vLLM loaders
        "vllm-smolvlm": VLLMSmolVLM,
        "vllm-smolvlm-256m": lambda **kwargs: VLLMSmolVLM(
            "HuggingFaceTB/SmolVLM-256M-Instruct", **kwargs
        ),
        "vllm-smolvlm-500m": lambda **kwargs: VLLMSmolVLM(
            "HuggingFaceTB/SmolVLM-500M-Instruct", **kwargs
        ),
        "vllm-smolvlm-2.2b": lambda **kwargs: VLLMSmolVLM(
            "HuggingFaceTB/SmolVLM2-2.2B-Instruct", **kwargs
        ),
        "vllm-moondream": VLLMMoondreamVLM,
        "vllm-qwen": VLLMQwenVLM,
        # -- AutoCausal loaders
        "smolvlm": SmolVLM,
        "smolvlm-256m": lambda **kwargs: SmolVLM(
            "HuggingFaceTB/SmolVLM-256M-Instruct", **kwargs
        ),
        "smolvlm-500m": lambda **kwargs: SmolVLM(
            "HuggingFaceTB/SmolVLM-500M-Instruct", **kwargs
        ),
        "smolvlm-2.2b": lambda **kwargs: SmolVLM(
            "HuggingFaceTB/SmolVLM2-2.2B-Instruct", **kwargs
        ),
        "moondream": MoondreamVLM,
        "qwen": QwenVLM,
    }

    @classmethod
    def create_vlm(cls, model_type: str, **kwargs) -> BaseVLM:
        """Create a VLM instance based on model type.

        Parameters
        ----------
        model_type : str
            Model type.
        **kwargs
            Additional arguments for VLM initialization

        Returns
        -------
        BaseVLM
            VLM instance.
        """
        model_type = model_type.lower()

        if model_type not in cls._models:
            available = list(cls._models.keys())
            raise ValueError(
                f"Unsupported model type: {model_type}. Available: {available}"
            )

        model_class = cls._models[model_type]
        if callable(model_class):
            return model_class(**kwargs)
        else:
            return model_class(**kwargs)

    @classmethod
    def get_available_models(cls) -> list[str]:
        """Get list of available model types.

        Returns
        -------
        list[str]
            List of available model types.
        """
        return list(cls._models.keys())


class VLMProcessor:
    def __init__(
        self,
        model_type: str = None,
        max_workers: int = None,
        skip_large_images: bool = None,
        **kwargs,
    ):
        """Initialize VLM processor.

        Parameters
        ----------
        model_type : str, optional
            Type of VLM to use (prefer vllm-* variants for speed).
            If None, uses the default from configuration.
        max_workers : int, optional
            Maximum number of concurrent VLM workers.
            If None, uses the default from configuration.
        skip_large_images : bool, optional
            If True, skip VLM analysis for images that are too large.
            If None, uses the default from configuration.
        **kwargs
            Additional arguments for VLM initialization
        """
        config = _vlm_config()

        if model_type is None:
            model_type = config.vlm_model
        if max_workers is None:
            max_workers = config.vlm_workers
        if skip_large_images is None:
            skip_large_images = config.skip_large_images

        self.model_type = model_type
        self.max_workers = max_workers
        self.skip_large_images = skip_large_images
        self.vlm = VLMLoader.create_vlm(model_type, **kwargs)
        self.semaphore = asyncio.Semaphore(max_workers)

        # Statistics
        self.stats = {
            "images_processed": 0,
            "successful_analyses": 0,
            "failed_analyses": 0,
            "skipped_images": 0,
            "total_processing_time": 0.0,
        }

    async def analyze_image_async(self, image_path: str) -> VLMResult:
        """Analyze image

        Parameters
        ----------
        image_path : str
            Image path.

        Returns
        -------
        VLMResult
            Analysis result containing extracted text and description.
        """
        async with self.semaphore:
            try:
                result = await self.vlm.analyze_image(image_path)

                self.stats["total_processing_time"] += result.processing_time
                self.stats["images_processed"] += 1

                if result.confidence > 0:
                    self.stats["successful_analyses"] += 1
                elif "skipped" in result.description.lower():
                    self.stats["skipped_images"] += 1
                else:
                    self.stats["failed_analyses"] += 1

                return result

            except Exception as e:
                self.stats["failed_analyses"] += 1
                return VLMResult(
                    extracted_text="",
                    description=f"Analysis failed: {str(e)}",
                    confidence=0.0,
                    model_used=self.model_type,
                    processing_time=0.0,
                )

    async def analyze_images_batch(
        self, image_paths: list[str]
    ) -> dict[str, VLMResult]:
        """Analyze multiple images concurrently

        Parameters
        ----------
        image_paths : list[str]
            Image path.

        Returns
        -------
        dict[str, VLMResult]
            Analysis result containing extracted text and description.
        """
        tasks = [self.analyze_image_async(path) for path in image_paths]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # -- processing
        processed_results = {}
        for i, (path, result) in enumerate(zip(image_paths, results)):
            if isinstance(result, Exception):
                processed_results[path] = VLMResult(
                    extracted_text="",
                    description=f"Task failed: {str(result)}",
                    confidence=0.0,
                    model_used=self.model_type,
                    processing_time=0.0,
                )
            else:
                processed_results[path] = result

        return processed_results

    def format_vlm_result_for_markdown(self, result: VLMResult) -> str:
        """Format vlm result for markdown

        Parameters
        ----------
        result : VLMResult
            Analysis result containing extracted text and description.

        Returns
        -------
        str
            formatted image description.
        """
        if not result.extracted_text and not result.description:
            return ""

        markdown_lines = []
        markdown_lines.append("**Image Analysis:**")

        if result.extracted_text:
            markdown_lines.append(f"**OCR Text:** {result.extracted_text}")

        if result.description:
            markdown_lines.append(f"**Image description:** {result.description}")

        return "\n".join(markdown_lines)

    def get_stats_summary(self) -> str:
        if self.stats["images_processed"] == 0:
            return "No images processed"

        avg_time = self.stats["total_processing_time"] / self.stats["images_processed"]
        success_rate = (
            self.stats["successful_analyses"] / self.stats["images_processed"]
        ) * 100

        return (
            f"VLM Processing Summary:\n"
            f"- Images processed: {self.stats['images_processed']}\n"
            f"- Successful analyses: {self.stats['successful_analyses']}\n"
            f"- Failed analyses: {self.stats['failed_analyses']}\n"
            f"- Skipped images: {self.stats['skipped_images']}\n"
            f"- Success rate: {success_rate:.1f}%\n"
            f"- Average processing time: {avg_time:.2f}s per image\n"
            f"- Total processing time: "
            f"{self.stats['total_processing_time']:.2f}s"
        )


async def analyze_single_image(image_path: str, model_type: str = None) -> VLMResult:
    if model_type is None:
        model_type = _vlm_config().vlm_model

    processor = VLMProcessor(model_type=model_type)
    return await processor.analyze_image_async(image_path)


def get_supported_models() -> list[str]:
    return VLMLoader.get_available_models()
