"""Explicit fact/event graph with polarity, provenance and unresolved contradictions."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
DEFAULT_WORLD = ROOT / 'models/athenea.world.sqlite'


class WorldMemory:
    def __init__(self, path=DEFAULT_WORLD):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS facts (
                id TEXT PRIMARY KEY, subject TEXT, relation TEXT, object TEXT,
                polarity TEXT, kind TEXT, event_at TEXT, source TEXT,
                verified INTEGER, retired INTEGER DEFAULT 0, created_at TEXT)''')

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        return connection

    def add(self, subject, relation, object, *, polarity='positive', kind='fact',
            event_at='', source, verified=False):
        if not all(isinstance(v, str) and v.strip() for v in (subject, relation, object, source)):
            raise ValueError('Subject, relation, object and source are required')
        if polarity not in {'positive', 'negative'} or kind not in {'fact', 'event'}:
            raise ValueError('Invalid polarity or kind')
        if kind == 'event' and not event_at:
            raise ValueError('Events require an explicit ISO event date')
        if event_at:
            datetime.fromisoformat(event_at.replace('Z', '+00:00'))
        subject, relation, object = (v.strip() for v in (subject, relation, object))
        identity = hashlib.sha256(json.dumps([subject.casefold(), relation.casefold(), object.casefold(),
            polarity, kind, event_at, source], ensure_ascii=False).encode()).hexdigest()
        with self.connect() as connection:
            connection.execute('''INSERT INTO facts
                (id,subject,relation,object,polarity,kind,event_at,source,verified,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET verified=MAX(verified,excluded.verified)''',
                (identity,subject,relation,object,polarity,kind,event_at,source,int(verified),
                 datetime.now(timezone.utc).isoformat()))
        return identity

    def records(self, *, verified_only=False):
        with self.connect() as connection:
            rows = [dict(row) for row in connection.execute('SELECT * FROM facts WHERE retired=0')]
        def key(row):
            return tuple(str(row[field]).casefold() for field in ('subject','relation','object','kind','event_at'))
        verified_polarities = {}
        for row in rows:
            if row['verified']:
                verified_polarities.setdefault(key(row), set()).add(row['polarity'])
        for row in rows:
            row['contradiction'] = len(verified_polarities.get(key(row), set())) > 1
        return [row for row in rows if not verified_only or row['verified']]

    def retire(self, identity):
        with self.connect() as connection:
            cursor = connection.execute('UPDATE facts SET retired=1 WHERE id=?', (identity,))
            if cursor.rowcount != 1:
                raise ValueError('Unknown fact ID')

    def context(self, query, max_chars=1800):
        terms = set(re.findall(r'\w+', query.casefold()))
        rows = self.records(verified_only=True)
        ranked = sorted(rows, key=lambda row: len(terms & set(re.findall(r'\w+',
            ' '.join(row[k] for k in ('subject','relation','object')).casefold()))), reverse=True)
        selected, used = [], 0
        for row in ranked:
            if not terms & set(re.findall(r'\w+', ' '.join(row[k] for k in ('subject','relation','object')).casefold())):
                continue
            text = json.dumps(row, ensure_ascii=False)
            if used + len(text) <= max_chars:
                selected.append(text); used += len(text)
        return '\n'.join(selected)

    def training_rows(self):
        groups = {}
        for row in self.records(verified_only=True):
            if row['contradiction']:
                continue
            groups.setdefault((row['subject'], row['relation']), []).append(row)
        result = []
        for (subject, relation), rows in groups.items():
            answer = [{k: row[k] for k in ('object','polarity','kind','event_at','source','id')} for row in rows]
            result.append({'prompt': f'¿Qué indican los registros verificados sobre {subject} y {relation}?',
                           'completion': json.dumps(answer, ensure_ascii=False),
                           'source': 'world_memory_verified_nonconflicting'})
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=DEFAULT_WORLD)
    sub = parser.add_subparsers(dest='action', required=True)
    add = sub.add_parser('add')
    for name in ('subject','relation','object','source'):
        add.add_argument('--'+name, required=True)
    add.add_argument('--polarity', choices=['positive','negative'], default='positive')
    add.add_argument('--kind', choices=['fact','event'], default='fact')
    add.add_argument('--event-at', default='')
    add.add_argument('--verified', action='store_true')
    recall = sub.add_parser('recall'); recall.add_argument('query')
    retire = sub.add_parser('retire'); retire.add_argument('id')
    export = sub.add_parser('export'); export.add_argument('--output', type=Path, required=True)
    sub.add_parser('init')
    args = parser.parse_args(); memory = WorldMemory(args.database)
    if args.action == 'add':
        result = {'id': memory.add(args.subject,args.relation,args.object,source=args.source,
            polarity=args.polarity,kind=args.kind,event_at=args.event_at,verified=args.verified)}
    elif args.action == 'recall': result = memory.context(args.query)
    elif args.action == 'retire': memory.retire(args.id); result = {'retired': args.id}
    elif args.action == 'export':
        rows = memory.training_rows(); args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows))
        result = {'exported': len(rows)}
    else: result = {'database': str(memory.path), 'facts': len(memory.records())}
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':main()
