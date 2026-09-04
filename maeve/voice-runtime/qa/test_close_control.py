"""Authenticated shutdown unit tests; no listener, native API, or worker."""
from pathlib import Path
import sys, unittest
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'broker'))
import server as broker

class CloseControlTests(unittest.TestCase):
    def handler(self,authorized=True):
        handler=object.__new__(broker.MaeveHandler)
        handler.path='/api/runtime/close';handler.headers={'Origin':'http://127.0.0.1:48177'}
        handler._authorized=Mock(return_value=authorized)
        handler._read_json_body=Mock(return_value={'action':'close-maeve','runtimeVersion':broker.RUNTIME_VERSION})
        handler._finish=Mock();handler.server=type('FakeServer',(),{'shutdown':Mock()})()
        return handler
    def test_unauthenticated_shutdown_rejected(self):
        handler=self.handler(False)
        with patch.object(broker.threading,'Thread') as thread:handler.do_POST()
        self.assertEqual(handler._finish.call_args.args[0],404)
        handler._read_json_body.assert_not_called();thread.assert_not_called()
    def test_authenticated_shutdown_once(self):
        handler=self.handler()
        with patch.object(broker.threading,'Thread') as thread:
            handler.do_POST();handler.do_POST()
            self.assertEqual(thread.call_count,1);thread.return_value.start.assert_called_once()
            self.assertEqual(thread.call_args.kwargs['target'],handler.server.shutdown)
        self.assertEqual(handler._finish.call_count,2)
        self.assertEqual(handler._finish.call_args.args[0],200)
    def test_wrong_origin_rejected(self):
        handler=self.handler();handler.headers['Origin']='https://invalid.example'
        with patch.object(broker.threading,'Thread') as thread:handler.do_POST()
        self.assertEqual(handler._finish.call_args.args[0],403);thread.assert_not_called()
    def test_malformed_close_rejected(self):
        handler=self.handler();handler._read_json_body.return_value={'action':'close-maeve'}
        with patch.object(broker.threading,'Thread') as thread:handler.do_POST()
        self.assertEqual(handler._finish.call_args.args[0],400);thread.assert_not_called()
    def test_startup_failure_option_and_guards_preserved(self):
        html=(ROOT/'ui/index.html').read_text(encoding='utf-8')
        self.assertIn('id="close-maeve"',html)
        js=(ROOT/'ui/scripts/close-control.js').read_text(encoding='utf-8')
        self.assertIn('CLOSE MAEVE?',js);self.assertIn('if(attempted||!config.authorized)return',js)
        runtime=(ROOT/'ui/scripts/runtime.js').read_text(encoding='utf-8')
        self.assertIn('await conversationController?.prepareRuntimeClose()',runtime)
        self.assertIn('headers.set("X-Maeve-Token",runtimeToken)',runtime)
        self.assertNotIn('onMicAmplitude',runtime)
