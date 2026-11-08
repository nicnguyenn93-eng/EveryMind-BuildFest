"""Opt-in, offline checks of the installed English and Spanish models.

These examples expose limitations; they do not assert perfect PII detection.
The detailed synthetic-only report is written to ignored private_data/.
"""

from dataclasses import asdict
import json
import os
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from scripts.redact_pii import PRIVATE_DATA, build_redactor


# Fictional examples only. Target spans are review prompts, not a gold-standard
# evaluation set; some identifying context requires policy beyond generic PII.
CASES = [
    ("en_name", "en", "My name is Alice Johnson and I appreciated the training.", [("name", "Alice Johnson")]),
    ("en_email", "en", "Please email alice@example.com for my feedback.", [("email", "alice@example.com")]),
    ("en_phone", "en", "Call me at 202-555-0123.", [("phone", "202-555-0123")]),
    ("en_address", "en", "I live at 123 Maple Street, Springfield, Illinois.", [("address", "123 Maple Street"), ("location", "Springfield"), ("location", "Illinois")]),
    ("en_school", "en", "I work at Cedar Valley High School.", [("school", "Cedar Valley High School")]),
    ("en_organization", "en", "I work for Acme Corporation.", [("organization", "Acme Corporation")]),
    ("en_initials", "en", "The presenter J.R. answered my questions.", [("name", "J.R.")]),
    ("en_context", "en", "I am the only school counselor in my county who trained this month.", [("contextual_identifier", "only school counselor in my county")]),
    ("en_short_name", "en", "Thanks Alex for explaining everything.", [("name", "Alex")]),
    ("en_harmless", "en", "I learned how to call 988, listen, and offer support.", []),
    ("en_harmless_time", "en", "The training last Monday was useful; next time allow two hours.", []),
    ("es_name", "es", "Me llamo María García y la capacitación fue útil.", [("name", "María García")]),
    ("es_email", "es", "Mi correo es maria@example.com para enviar comentarios.", [("email", "maria@example.com")]),
    ("es_phone", "es", "Mi teléfono es +34 612 345 678.", [("phone", "+34 612 345 678")]),
    ("es_address", "es", "Vivo en Calle Mayor 10, Madrid.", [("address", "Calle Mayor 10"), ("location", "Madrid")]),
    ("es_school", "es", "Trabajo en el Colegio Valle Verde.", [("school", "Colegio Valle Verde")]),
    ("es_organization", "es", "Trabajo para Acme Corporation.", [("organization", "Acme Corporation")]),
    ("es_context", "es", "Soy la única orientadora escolar de mi condado.", [("contextual_identifier", "única orientadora escolar de mi condado")]),
    ("es_short_name", "es", "Gracias Ana por explicar todo.", [("name", "Ana")]),
    ("es_harmless", "es", "Aprendí a escuchar y a pedir ayuda al 988.", []),
]


@unittest.skipUnless(os.environ.get("RUN_PRESIDIO_INTEGRATION") == "1", "Set RUN_PRESIDIO_INTEGRATION=1 after installing the models.")
class InstalledModelTests(unittest.TestCase):
    def test_cpu_offline_models_and_record_detection_gaps(self):
        import spacy
        from thinc.api import get_current_ops
        report = []
        # Block DNS, socket connections, downloads, and GPU activation even on a
        # fresh machine without a tldextract cache. Any attempted use fails.
        with patch.object(socket.socket, "connect", side_effect=AssertionError("Network connection attempted")), \
             patch.object(socket.socket, "connect_ex", side_effect=AssertionError("Network connection attempted")), \
             patch.object(socket, "getaddrinfo", side_effect=AssertionError("DNS attempted")), \
             patch.object(spacy.cli, "download", side_effect=AssertionError("Model download attempted")), \
             patch.object(spacy, "require_gpu", side_effect=AssertionError("GPU requested")):
            engine = build_redactor()
            self.assertEqual("NumpyOps", type(get_current_ops()).__name__)
            for name, language, text, targets in CASES:
                result = engine.redact(text, language)
                covered = {i for detection in result.detections for i in range(detection.start, detection.end)}
                checks = []
                for category, value in targets:
                    start = text.index(value)
                    span = set(range(start, start + len(value)))
                    overlap = span & covered
                    checks.append({
                        "category": category, "target": value,
                        "coverage": "complete" if overlap == span else "partial" if overlap else "missed",
                    })
                report.append({
                    "case": name, "language": language, "text": text,
                    "redacted": result.text,
                    "detections": [asdict(detection) for detection in result.detections],
                    "targets": checks,
                    "harmless_text_changed": not targets and result.text != text,
                })
            for name in ("en_email", "es_email", "en_phone", "es_phone"):
                case = next(case for case in report if case["case"] == name)
                self.assertTrue(case["detections"], name)
        PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        destination = PRIVATE_DATA / "presidio_synthetic_review.json"
        destination.write_text(json.dumps({"versions": engine.versions, "cases": report}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
