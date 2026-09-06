#!/usr/bin/env python3
"""Read a page of public conversation text for attachment to the current chat."""
import argparse
import json
from pathlib import Path

from fork_context import _reject_secrets
from resolve_session import _json_records, resolve_session


def messages(source):
    path = source.get('native_record')
    if not path:
        raise ValueError('native_history_unavailable')
    for record in _json_records(Path(path)):
        if source['provider'] == 'codex':
            if record.get('type') != 'response_item':
                continue
            message = record.get('payload', {})
            if message.get('type') != 'message':
                continue
        else:
            if record.get('type') not in ('user', 'assistant') or record.get('isSidechain'):
                continue
            message = record.get('message', {})
        role = message.get('role', record.get('type'))
        if role not in ('user', 'assistant'):
            continue
        content = message.get('content', [])
        if isinstance(content, str):
            text = content
        else:
            text = '\n'.join(
                block.get('text', '') for block in content
                if isinstance(block, dict) and block.get('type') in ('text', 'input_text', 'output_text')
            )
        if text:
            _reject_secrets(text)
            yield {'role': role, 'text': text}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session_id')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--limit', type=int, default=10)
    args = parser.parse_args()
    if args.offset < 0 or args.limit < 1:
        parser.error('offset must be nonnegative and limit positive')
    source = resolve_session(args.session_id)
    records = list(messages(source))
    end = min(len(records), args.offset + args.limit)
    print(json.dumps({'source': source, 'records': records[args.offset:end],
                      'next_offset': end if end < len(records) else None,
                      'total_records': len(records),
                      'coverage': 'public text only; tool results and attachments excluded'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
