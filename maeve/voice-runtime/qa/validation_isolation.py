"""Test-only provider injection. Never consult native credentials or default ledger."""
from contextlib import contextmanager, ExitStack
from pathlib import Path
import tempfile
from unittest.mock import patch

def forbidden(*args, **kwargs):
    raise AssertionError('UNEXPECTED_PRIVATE_STATE_ACCESS')

@contextmanager
def isolated_broker(broker):
    import voice_provider
    original = voice_provider.ElevenLabsProvider
    with tempfile.TemporaryDirectory(prefix='maeve-qa-ledger-') as directory, ExitStack() as stack:
        directory = Path(directory).resolve()
        runtime = Path(__file__).resolve().parent.parent
        assert not directory.is_relative_to(runtime)
        for name in ('credential_read','credential_write','credential_remove','_credential_api','default_ledger'):
            stack.enter_context(patch.object(voice_provider,name,side_effect=forbidden))
        providers=[]
        def factory():
            ledger=voice_provider.UsageLedger(directory / ('counts-'+str(len(providers))+'.json'))
            # Construct the obvious non-secret sentinel in memory; never serialize it.
            reader=lambda: ''.join(chr(n) for n in (78,79,84,95,65,95,83,69,67,82,69,84,95,81,65,95,79,78,76,89))
            provider=original(ledger=ledger,credential_reader=reader,opener=forbidden,voice_id='V'*20)
            providers.append(provider)
            return provider
        stack.enter_context(patch.object(broker,'ElevenLabsProvider',side_effect=factory))
        # Replace the import-time global's defaults too.
        stack.enter_context(patch.object(broker.VOICE,'cloud',factory()))
        yield providers, directory
