import unittest

from inventory.maeve_visual_inspection import (
    ExternalCameraSource,
    ReadOnlyVisualInspectionGate,
    VisualEvidence,
)


class MaeveVisualInspectionTests(unittest.TestCase):
    def test_external_camera_is_disabled_without_hardware(self):
        ExternalCameraSource().validate()

    def test_external_camera_rejects_public_or_secret_bearing_urls(self):
        for url in (
            "https://example.com/stream",
            "http://user:secret@127.0.0.1/stream",
            "http://127.0.0.1/stream?token=secret",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                ExternalCameraSource(True, url).validate()

    def test_external_camera_accepts_verified_private_source(self):
        ExternalCameraSource(True, "http://127.0.0.1:8080/stream").validate()

    def test_insufficient_or_obstructed_evidence_is_unverifiable(self):
        gate = ReadOnlyVisualInspectionGate()
        for evidence in (
            VisualEvidence(3, True, 0.99, 0.01, "first_layer"),
            VisualEvidence(8, False, 0.99, 0.01, "warp"),
        ):
            result = gate.decide(evidence)
            self.assertEqual(result.verdict, "unable_to_verify")
            self.assertFalse(result.control_capable)
            self.assertFalse(result.automatic_action)

    def test_high_confidence_problem_wins_and_never_controls(self):
        result = ReadOnlyVisualInspectionGate().decide(VisualEvidence(8, True, 0.92, 0.86, "warp"))
        self.assertEqual(result.verdict, "possible_problem")
        self.assertEqual(result.issue, "warp")
        self.assertFalse(result.control_capable)
        self.assertFalse(result.automatic_action)

    def test_good_requires_high_confidence_and_clear_problem_gate(self):
        gate = ReadOnlyVisualInspectionGate()
        self.assertEqual(gate.decide(VisualEvidence(8, True, 0.95, 0.10, "first_layer")).verdict, "looks_good")
        self.assertEqual(gate.decide(VisualEvidence(8, True, 0.75, 0.20, "first_layer")).verdict, "unable_to_verify")


if __name__ == "__main__":
    unittest.main()
