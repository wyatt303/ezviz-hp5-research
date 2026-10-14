#!/usr/bin/env python3
"""Probe CPD7 LAN media reception; no tokens or keys are printed."""
import argparse
import contextlib
import io
import os
from importlib.metadata import distribution
import logging
import sys
import time
from pathlib import Path


class _CasCaptured(BaseException):
    """Stop the CLI after CAS succeeds, before its old LAN path starts."""


def get_control_key(args):
    from pyezvizapi.cas import EzvizCAS, CasDeviceSession

    original = EzvizCAS.cas_get_encryption
    saved_argv = sys.argv
    saved_disable = logging.root.manager.disable
    captured = {}

    def intercept(self, *call_args, **call_kwargs):
        response = original(self, *call_args, **call_kwargs)
        session = (response if isinstance(response, CasDeviceSession)
                   else CasDeviceSession.from_response(response))
        captured['key'] = session.key.encode('ascii')
        raise _CasCaptured()

    entry = next(ep for ep in distribution('pyezvizapi').entry_points
                 if ep.group == 'console_scripts' and ep.name == 'pyezvizapi')
    sys.argv = [
        'pyezvizapi', '--token-file', args.token_file,
        'stream', 'local-sdk-dump', '--host', args.host,
        '--serial', args.cas_serial, '--cas-serial', args.cas_serial,
        '--fetch-cas', '--duration', '1s', '--format', 'mpegps',
        '--output', os.devnull,
    ]
    EzvizCAS.cas_get_encryption = intercept
    try:
        # Remote errors can contain session material: suppress CLI output.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            logging.disable(logging.CRITICAL)
            try:
                entry.load()()
            except _CasCaptured:
                pass
            except SystemExit:
                pass
    finally:
        EzvizCAS.cas_get_encryption = original
        sys.argv = saved_argv
        logging.disable(saved_disable)
    if 'key' not in captured:
        raise RuntimeError('CLI did not provide a CAS control key')
    return captured['key']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='hp5-lan')
    parser.add_argument('--token-file', default='ezviz_token.json')
    parser.add_argument('--host', default='192.168.1.47')
    parser.add_argument('--cas-serial', default='SCREEN_SERIAL')
    parser.add_argument('--related-device', default='CAMERA_SERIAL',
                        help='Paired camera identifier sent as Channel RelatedDevice; verify device mapping')
    parser.add_argument('--duration', type=float, default=15)
    args = parser.parse_args()
    if args.duration <= 0:
        parser.error('--duration must be positive')

    module_root = Path(args.repo).resolve() / 'custom_components' / 'ezviz_hp7'
    if not (module_root / 'cpd7' / 'lan_client.py').is_file():
        parser.error(f'CPD7 client missing under {module_root}')
    sys.path.insert(0, str(module_root))
    stage = 'imports'
    lan = None
    try:
        from cpd7.lan_client import Cpd7LanClient

        # Only CPD7 debug logs: the supplied client logs command numbers/lengths.
        logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
        logging.getLogger('cpd7.lan_client').setLevel(logging.DEBUG)
        stage = 'CAS session through installed CLI'
        key = get_control_key(args)
        if len(key) != 16:
            raise ValueError('CAS control key must be 16 ASCII bytes')
        print('CAS control key obtained (value hidden).', flush=True)
        stage = 'CPD7 INIT / INVITE / PLAY'
        lan = Cpd7LanClient(
            host=args.host, related_device=args.related_device, aes_key=key,
            channel=1, stream_quality='main', encrypt_stream=True,
            recv_timeout=5.0,
        )
        lan.start()
        print('CPD7 handshake completed; waiting for media.', flush=True)
        stage = 'media reception'
        deadline = time.monotonic() + args.duration
        chunks = total = 0
        while time.monotonic() < deadline:
            chunk = lan.read_chunk()
            if not chunk:
                print('No more data: read timeout or connection closed.', flush=True)
                break
            chunks += 1
            total += len(chunk)
            if chunks == 1:
                print(f'FIRST DATA: {len(chunk)} bytes.', flush=True)
        print(f'RESULT: {chunks} chunks, {total} bytes received.', flush=True)
        print('Payload is not decoded in this probe.', flush=True)
        return 0 if total else 2
    except Exception as exc:
        # Exception messages from remote/session parsers may contain secrets.
        print(f'FAILED at {stage}: {type(exc).__name__}. Details suppressed.', file=sys.stderr)
        if isinstance(exc, ModuleNotFoundError):
            print(f'Missing Python module: {exc.name}', file=sys.stderr)
        elif isinstance(exc, AttributeError):
            print('Installed API differs from the expected interface.', file=sys.stderr)
        return 1
    finally:
        if lan is not None:
            lan.close()


if __name__ == '__main__':
    sys.exit(main())

