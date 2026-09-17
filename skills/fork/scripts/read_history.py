#!/usr/bin/env python3
"""Read a page of public conversation text for attachment to the current chat."""
import argparse
import json
import sqlite3
from pathlib import Path

from fork_context import _reject_secrets
from resolve_session import ResolveError, _json_records, _t3_connection, resolve_session


def _t3_messages(source):
    path = source.get('source_record')
    thread_id = source.get('t3_thread_id')
    boundary = source.get('boundary')
    boundary_turn_id = boundary.get('turn_id') if isinstance(boundary, dict) else None
    if not path or not thread_id or not boundary_turn_id:
        raise ValueError('t3_history_unavailable')

    try:
        connection = _t3_connection(Path(path))
    except ResolveError as exc:
        raise ValueError('t3_history_unavailable') from exc
    try:
        boundary_record = connection.execute(
            """
            SELECT row_id
            FROM projection_turns
            WHERE thread_id = ? AND turn_id = ?
            """,
            (thread_id, boundary_turn_id),
        ).fetchone()
        if boundary_record is None:
            raise ValueError('t3_history_unavailable')

        records = connection.execute(
            """
            SELECT messages.role, messages.text
            FROM projection_thread_messages AS messages
            JOIN projection_turns AS turns
                ON turns.thread_id = messages.thread_id
                AND (
                    turns.turn_id = messages.turn_id
                    OR turns.pending_message_id = messages.message_id
                    OR turns.assistant_message_id = messages.message_id
                )
            WHERE messages.thread_id = ?
                AND messages.role IN ('user', 'assistant')
                AND messages.is_streaming = 0
                AND turns.state = 'completed'
                AND turns.completed_at IS NOT NULL
                AND turns.row_id <= ?
            ORDER BY messages.created_at, messages.message_id
            """,
            (thread_id, boundary_record['row_id']),
        )
        for record in records:
            role = record['role']
            text = record['text']
            if role not in ('user', 'assistant') or not isinstance(text, str) or not text:
                continue
            _reject_secrets(text)
            yield {'role': role, 'text': text}
    except sqlite3.Error as exc:
        raise ValueError('t3_history_unavailable') from exc
    finally:
        connection.close()


def messages(source):
    if source.get('input_kind') == 't3':
        yield from _t3_messages(source)
        return

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
