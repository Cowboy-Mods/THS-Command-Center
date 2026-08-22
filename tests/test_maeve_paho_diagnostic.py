import ast
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "maeve_paho_test_once.py"


class MaevePahoDiagnosticTests(unittest.TestCase):
    def test_forbidden_paho_methods_are_never_called(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        forbidden = {"publish", "will_set", "reconnect", "loop_forever"}
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertEqual(calls & forbidden, set())

    def test_wrapper_exposes_only_run_operation(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        wrapper = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "SubscribeOnlyPahoDiagnostic"
        )
        public_methods = {
            node.name
            for node in wrapper.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        }
        self.assertEqual(public_methods, {"run"})

    def test_protocol_topic_and_reconnect_guards_are_explicit(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("protocol=mqtt.MQTTv311", source)
        self.assertIn("clean_session=True", source)
        self.assertIn("reconnect_on_failure=False", source)
        self.assertIn('active.subscribe(topic, qos=0)', source)
        self.assertIn('f"device/{serial}/report"', source)
        self.assertNotIn('/request', source)
        self.assertNotIn('"#"', source)
        self.assertNotIn('"+"', source)

    def test_packet_counter_distinguishes_connect_subscribe_and_publish(self):
        spec = importlib.util.spec_from_file_location("maeve_paho_test_once", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        counts = module.PacketCounts()
        counts.record(0x10)
        counts.record(0x82)
        counts.record(0x30)
        counts.record(0xE0)
        self.assertEqual(counts.connect, 1)
        self.assertEqual(counts.subscribe, 1)
        self.assertEqual(counts.outgoing_publish, 1)
        self.assertEqual(counts.other, {"14": 1})


if __name__ == "__main__":
    unittest.main()
