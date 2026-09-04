"""Run portable QA with synthetic state and fail-closed isolation."""
import ast
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'qa'))
sys.path.insert(0, str(ROOT / 'broker'))
os.chdir(ROOT)
sys.dont_write_bytecode = True

def main():
    with tempfile.TemporaryDirectory(prefix='maeve-public-qa-') as directory:
        os.environ['MAEVE_QA_ROOT'] = str(ROOT)
        os.environ['MAEVE_QA_TEMP'] = directory
        tempfile.tempdir = directory
        from rehearsal_guard import install
        install()
        import server as broker
        from validation_isolation import isolated_broker
        with isolated_broker(broker):
            import test_portable_config
            test_portable_config.main()
            import test_broker
            test_broker.main()
            import test_conversation
            test_conversation.main()
            suite = unittest.defaultTestLoader.discover(str(ROOT / 'qa'))
            result = unittest.TextTestRunner(verbosity=1).run(suite)
            if not result.wasSuccessful():
                raise SystemExit(1)
        for source in ROOT.rglob('*.py'):
            ast.parse(source.read_text(encoding='utf-8'), filename=source.relative_to(ROOT).as_posix())
        print('PUBLIC_STATIC_QA=PASS native_credentials=0 real_ledgers=0 external_network=0 operational_workers=0')

if __name__ == '__main__':
    main()
