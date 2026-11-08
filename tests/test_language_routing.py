"""Routing decisions and their privacy boundary, using fictional responses."""

from importlib import metadata
import socket
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from everymind_cleaning import everymind_clean as ec
from everymind_cleaning import language_routing as routing


def scores(english):
    return [SimpleNamespace(language=SimpleNamespace(iso_code_639_1=SimpleNamespace(name=code)), value=value)
            for code, value in (("EN", english), ("ES", 1 - english))]


class LanguageRoutingTests(unittest.TestCase):
    def test_threshold_boundary_and_flagged_fallback(self):
        detector = Mock()
        with patch.object(routing, "get_detector", return_value=detector):
            for english, expected, source in ((0.8, "en", "text"), (0.799999, "es", "form_fallback"),
                                               (0.5, "es", "form_fallback"), (0.1, "es", "text")):
                with self.subTest(score=english):
                    detector.compute_language_confidence_values.return_value = scores(english)
                    result = routing.resolve_language("A fictional response", "es")
                    self.assertEqual((expected, source), (result.language, result.language_source))
                    self.assertEqual(source == "form_fallback", result.language_review_required)
                    self.assertAlmostEqual(max(english, 1 - english), result.language_confidence)
            detector.compute_language_confidence_values.return_value = scores(0.8)
            self.assertEqual("es", routing.resolve_language("A response", "es", 0.9).language)
            self.assertEqual("en", routing.resolve_language("A response", "es", 0.7).language)

    def test_nonlinguistic_and_ambiguous_answers_never_guess(self):
        texts = ["???", "988", "24/7", "202-555-0123", "+1 (202) 555-0123", "no", "NO!", "N/A",
                 "N.A.", "na", "ok", "ada@example.com", "https://example.com/contact", "www.example.com",
                 "example.org", "ada@example.com +1 (202) 555-0123", "😊"]
        with patch.object(routing, "get_detector", side_effect=AssertionError("Should not guess")):
            for text in texts:
                for form in ("en", "es"):
                    with self.subTest(text=text, form=form):
                        decision = routing.resolve_language(text, form)
                        self.assertEqual((form, "unknown", None, "form_fallback", True),
                                         tuple(vars(decision).values()))

    def test_blanks_and_unresolved(self):
        with patch.object(routing, "get_detector", side_effect=AssertionError("No text evidence")):
            for text in ("", " \t\n"):
                result = routing.resolve_language(text)
                self.assertEqual(("none", "none", None, "blank", False), tuple(vars(result).values()))
            for form in ("unknown", "", "fr", None):
                result = routing.resolve_language("988", form)
                self.assertEqual(("unknown", "unresolved", True),
                                 (result.language, result.language_source, result.language_review_required))

    def test_invalid_thresholds_fail(self):
        for threshold in (0.5, 0, 1.01, True, "0.8", None, float("nan"), float("inf")):
            with self.subTest(threshold=threshold), self.assertRaises(routing.LanguageDetectionError):
                routing.resolve_language("", "en", threshold)

    def test_detector_failures_are_sanitized(self):
        with patch.object(routing, "get_detector", side_effect=RuntimeError("secret response text")):
            with self.assertRaises(routing.LanguageDetectionError) as error:
                routing.resolve_language("secret response text", "en")
        self.assertNotIn("secret", str(error.exception))
        detector = Mock()
        for values in ([], scores(float("nan")), scores(1.5)):
            detector.compute_language_confidence_values.return_value = values
            with patch.object(routing, "get_detector", return_value=detector):
                with self.assertRaises(routing.LanguageDetectionError):
                    routing.resolve_language("A fictional response", "en")

    def test_missing_or_incompatible_package_fails(self):
        with patch.object(routing.metadata, "version", side_effect=metadata.PackageNotFoundError("secret")):
            with self.assertRaises(routing.LanguageDetectionError) as error:
                routing.detector_metadata()
            self.assertNotIn("secret", str(error.exception))
        with patch.object(routing.metadata, "version", return_value="99"):
            with self.assertRaises(routing.LanguageDetectionError):
                routing.detector_metadata()

    def test_real_detector_is_cached_and_offline(self):
        routing.get_detector.cache_clear()
        self.addCleanup(routing.get_detector.cache_clear)
        cases = [
            ("La información.", "en", "es"),
            ("Como ayudar a las personas en crisis", "en", "es"),
            ("Aprendi como alludar a mi familia", "en", "es"),
            ("Lo mas valioso fue aprender como usar el hotline", "en", "es"),
            ("Learning how to support someone in crisis.", "es", "en"),
            ("Thank you for explaining how the servicio works.", "es", "en"),
        ]
        with patch.object(socket.socket, "connect", side_effect=AssertionError("Network attempted")), \
             patch.object(socket.socket, "connect_ex", side_effect=AssertionError("Network attempted")), \
             patch.object(socket, "getaddrinfo", side_effect=AssertionError("DNS attempted")):
            self.assertIs(routing.get_detector(), routing.get_detector())
            for text, form, expected in cases:
                with self.subTest(text=text):
                    result = routing.resolve_language(text, form)
                    self.assertEqual((expected, "text", False),
                                     (result.language, result.language_source, result.language_review_required))
            self.assertEqual("es", ec.detect_language("La información.", "en"))
            self.assertEqual("none", ec.detect_language(""))


if __name__ == "__main__":
    unittest.main()
