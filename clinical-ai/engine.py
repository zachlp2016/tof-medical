"""Bounded, local OpenMed inference. Request data lives only in call-local memory."""
import math
import re
import threading
import time
from pathlib import Path
from artifacts import verify_bundle

# Supplement model spans with complete ASCII email addresses. The leading
# boundary prevents repeated scans inside long local parts; the domain stops
# before sentence punctuation. This is not a complete identifier detector.
EMAIL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9.!#$%&'*+/=?^_`{|}~-])"
    r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
    r"(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
)


class WorkerBusy(Exception):
    pass


def merge_word_fragments(text: str, entities: list[dict]) -> list[dict]:
    """Join same-label model fragments only across an internal word boundary."""
    merged = []
    for entity in sorted(entities, key=lambda item: (item["start"], item["end"])):
        boundary = entity["start"]
        if (merged and merged[-1]["label"] == entity["label"]
                and merged[-1]["end"] == boundary
                and text[boundary - 1].isalnum() and text[boundary].isalnum()):
            previous = merged[-1]
            previous["end"] = entity["end"]
            previous["text"] = text[previous["start"]:entity["end"]]
            previous["confidence"] = min(previous["confidence"], entity["confidence"])
        else:
            merged.append(dict(entity))
    return merged


class Engine:
    def __init__(self, root: Path):
        self.lock = verify_bundle(root)
        import importlib.metadata
        if importlib.metadata.version("openmed") != self.lock["sdkVersion"]:
            raise RuntimeError("Unexpected SDK version")
        import onnxruntime as ort
        from openmed import OnnxModel
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.log_severity_level = 4
        self.models = {
            operation: OnnxModel.from_pretrained(
                root / operation, variant="int8", local_files_only=True,
                providers=("CPUExecutionProvider",), session_options=options,
            )
            for operation in self.lock["models"]
        }
        self.gate = threading.Lock()

    def review(self, text: str, operation: str) -> dict:
        if not self.gate.acquire(blocking=False):
            raise WorkerBusy()
        try:
            return self._review(text, operation)
        finally:
            self.gate.release()

    def _review(self, text: str, operation: str) -> dict:
        from openmed.onnx.execution import OnnxExecutionControl
        start = time.monotonic()
        result = self.models[operation].predict_batch_detailed(
            [text], threshold=0.0, max_length=512, stride=96,
            batch_size=1, max_batch_tokens=512, max_windows=128,
            execution_control=OnnxExecutionControl(timeout_seconds=100),
        )[0]
        if not result.complete or result.processed_tokens != result.token_count:
            raise RuntimeError("Incomplete document coverage")
        entities = []
        for item in result.entities:
            if not (0 <= item.start < item.end <= len(text)):
                raise RuntimeError("Invalid source offsets")
            if text[item.start:item.end] != item.text or not math.isfinite(item.score):
                raise RuntimeError("Invalid entity projection")
            if not 0 <= item.score <= 1 or len(item.label) > 128:
                raise RuntimeError("Invalid entity metadata")
            entities.append({"text": item.text, "label": item.label,
                             "start": item.start, "end": item.end,
                             "confidence": round(float(item.score), 6)})
        provenance = self.lock["models"][operation]
        output = {"operation": operation, "entities": [],
                  "model": {key: provenance[key] for key in ("id", "revision")}}
        if operation == "deidentify":
            # Merge all predicted PII intervals, even low-confidence candidates.
            # Never serialize OpenMed's raw de-identification/PII result objects.
            spans = [(entity["start"], entity["end"]) for entity in entities]
            spans.extend(match.span() for match in EMAIL_PATTERN.finditer(text))
            merged = []
            for left, right in sorted(spans):
                if merged and left <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], right)
                else:
                    merged.append([left, right])
            parts, cursor = [], 0
            for left, right in merged:
                parts.extend((text[cursor:left], "[REDACTED]"))
                cursor = right
            parts.append(text[cursor:])
            output.update(redactedText="".join(parts), redactionCount=len(merged), warnings=[
                "Automated PII redaction may miss identifiers; clinician review is required before sharing.",
                "This English-language model does not establish legal de-identification or anonymization.",
            ])
        else:
            entities = merge_word_fragments(text, entities)
            if len(entities) > 1000:
                raise RuntimeError("Entity result limit exceeded")
            output.update(entities=entities, warnings=[
                "Disease and condition mentions only; medications, laboratory values, and other entity types are outside this model's scope.",
                "Mentions are not diagnoses. Negation, temporality, and experiencer are not assessed.",
            ])
        output["durationMs"] = round((time.monotonic() - start) * 1000)
        return output
