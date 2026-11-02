#!/usr/bin/env python3
"""Local SQLite inventory for DSH test hosts; never launches or stops a host."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from urllib.parse import urlsplit


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def path(value):
    return str(Path(value).expanduser().resolve())


def default_db():
    root = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state'))
    return root / 'dsh-plugin-isolated-test/environments.sqlite3'


def origin(value):
    u = urlsplit(value)
    if (u.scheme not in ('http', 'https') or u.hostname not in ('127.0.0.1', 'localhost', '::1')
            or u.username or u.password or u.query or u.fragment or u.path not in ('', '/')
            or u.port is None):
        raise ValueError('URL must be a loopback origin with explicit port, without credentials/query/path')
    return f'{u.scheme}://{u.netloc}'


def run(*args):
    """Capture process metadata privately; do not echo commands or environment."""
    result = subprocess.run(args, capture_output=True, text=True, timeout=5,
                            env={**os.environ, 'LC_ALL': 'C'})
    return result.stdout.strip() if result.returncode == 0 else ''


def fingerprint(pid):
    if pid <= 0:
        raise ValueError('PID must be positive')
    value = run('ps', '-p', str(pid), '-o', 'lstart=', '-o', 'args=')
    return hashlib.sha256(value.encode()).hexdigest() if value else None


class Registry:
    def __init__(self, filename):
        filename = Path(filename).expanduser()
        filename.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Restrictive creation permissions also cover transient SQLite journals.
        old_mask = os.umask(0o077)
        try:
            self.db = sqlite3.connect(filename, timeout=10)
            filename.chmod(0o600)
            self.db.row_factory = sqlite3.Row
            self.db.execute('PRAGMA foreign_keys=ON')
            version = self.db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise ValueError(f'Unsupported registry version: {version}')
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS environments (
                    id TEXT PRIMARY KEY, project TEXT NOT NULL, home TEXT NOT NULL UNIQUE,
                    preferred INTEGER NOT NULL DEFAULT 0, data TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS project_preferred
                    ON environments(project) WHERE preferred=1;
                CREATE TABLE IF NOT EXISTS cases (
                    environment_id TEXT NOT NULL REFERENCES environments(id),
                    id TEXT NOT NULL, workspace TEXT NOT NULL, session_id TEXT,
                    purpose TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(environment_id,id));
                PRAGMA user_version=1;
            ''')
        finally:
            os.umask(old_mask)

    def close(self):
        self.db.close()

    def get(self, ident):
        row = self.db.execute('SELECT * FROM environments WHERE id=?', (ident,)).fetchone()
        if row is None:
            raise ValueError(f'Unknown environment: {ident}')
        result = dict(row)
        result.update(json.loads(result.pop('data')))
        result['preferred'] = bool(result['preferred'])
        result['cases'] = [dict(r) for r in self.db.execute(
            'SELECT id,workspace,session_id,purpose,updated_at FROM cases WHERE environment_id=? ORDER BY updated_at DESC', (ident,))]
        return result

    def list(self, project=None):
        rows = self.db.execute(
            'SELECT id FROM environments' + (' WHERE project=?' if project else '')
            + ' ORDER BY preferred DESC,updated_at DESC', (path(project),) if project else ())
        return [self.get(r['id']) for r in rows.fetchall()]

    def register(self, ident, project, home, data, preferred=False, reason=None):
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', ident):
            raise ValueError('Environment ID must use lowercase letters, digits, hyphen or underscore')
        project, home = path(project), path(home)
        if preferred and data['state'] == 'retired':
            raise ValueError('A retired environment cannot be preferred')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            existing = [r for r in self.list(project) if r['state'] != 'retired']
            if existing and not reason:
                raise ValueError('Project already has an environment; inspect and reuse it, or record --reason for another')
            data = {**data, 'separation_reason': reason}
            if preferred:
                self.db.execute('UPDATE environments SET preferred=0 WHERE project=?', (project,))
            self.db.execute('INSERT INTO environments VALUES (?,?,?,?,?,?,?)',
                            (ident, project, home, int(preferred), json.dumps(data), now(), now()))
        return self.get(ident)

    def update(self, ident, fields, preferred=False):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            current = self.get(ident)
            row = self.db.execute('SELECT data FROM environments WHERE id=?', (ident,)).fetchone()
            data = {**json.loads(row['data']), **fields}
            if preferred and data['state'] == 'retired':
                raise ValueError('A retired environment cannot be preferred')
            if preferred:
                self.db.execute('UPDATE environments SET preferred=0 WHERE project=?', (current['project'],))
            target = preferred or current['preferred']
            self.db.execute('UPDATE environments SET data=?,preferred=?,updated_at=? WHERE id=?',
                            (json.dumps(data), int(target and data['state'] != 'retired'), now(), ident))
        return self.get(ident)

    def bind(self, ident, case, workspace, purpose, session=None):
        self.get(ident)
        workspace = path(workspace)
        if not Path(workspace).is_dir():
            raise ValueError('Case workspace must exist')
        with self.db:
            self.db.execute('''INSERT INTO cases VALUES (?,?,?,?,?,?)
                ON CONFLICT(environment_id,id) DO UPDATE SET workspace=excluded.workspace,
                session_id=excluded.session_id,purpose=excluded.purpose,updated_at=excluded.updated_at''',
                            (ident, case, workspace, session, purpose, now()))
        return self.get(ident)


def check(record):
    """Read-only observations. Liveness is not model health or permission to redeploy."""
    missing = [key for key in ('home', 'source', 'plugin') if not Path(record[key]).is_dir()]
    missing_cases = [c['id'] for c in record['cases'] if not Path(c['workspace']).is_dir()]
    pid = record.get('pid')
    result = {'id': record['id'], 'checked_at': now(), 'missing_paths': missing,
              'missing_case_workspaces': missing_cases, 'process': 'unrecorded',
              'listener': 'unrecorded', 'cwd': 'unknown', 'home': 'unknown', 'profile': 'unknown',
              'live_identity_verified': False,
              'reuse_requires': 'Check task activity, profile/model and served artifact compatibility before mutation.'}
    if not pid:
        return result
    current = fingerprint(pid)
    result['process'] = ('not-running' if current is None else
                         'matches' if current == record.get('process_fingerprint') else 'identity-changed')
    if result['process'] != 'matches':
        return result
    command = run('ps', '-p', str(pid), '-o', 'args=')
    # Only comparisons leave this function; the captured environment may contain secrets.
    environment = run('ps', 'eww', '-p', str(pid), '-o', 'command=')
    # macOS /tmp and /private/tmp aliases are equivalent. Match a token, not a prefix.
    found = re.search(r'(?:^|\s)DSH_HOME=(.*?)(?=\s+[A-Za-z_][A-Za-z0-9_]*=|$)', environment)
    if found:
        result['home'] = 'matches' if path(found.group(1)) == record['home'] else 'mismatch'
    if re.search(r'(?:^|\s)--profile(?:=|\s+)' + re.escape(record['profile']) + r'(?:\s|$)', command):
        result['profile'] = 'matches'
    if shutil.which('lsof'):
        cwd = run('lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn')
        dirs = [line[1:] for line in cwd.splitlines() if line.startswith('n')]
        if dirs:
            result['cwd'] = 'matches' if path(dirs[0]) == record['source'] else 'mismatch'
        if record.get('url'):
            port = urlsplit(record['url']).port
            listeners = run('lsof', '-nP', f'-iTCP:{port}', '-sTCP:LISTEN', '-t').splitlines()
            result['listener'] = 'matches' if str(pid) in listeners else 'mismatch'
    result['live_identity_verified'] = (not missing and result['process'] == 'matches'
        and result['home'] == result['profile'] == result['cwd'] == 'matches'
        and (not record.get('url') or result['listener'] == 'matches'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default=str(default_db()), help='Persistent SQLite path (default: %(default)s)')
    sub = parser.add_subparsers(dest='command', required=True)
    listing = sub.add_parser('list', help='Find existing environments before creating one')
    listing.add_argument('--project', help='Canonical plugin project path, shared across test checkouts')
    for name in ('show', 'check'):
        sub.add_parser(name).add_argument('id')
    register = sub.add_parser('register', help='Register a verified deployment; does not deploy')
    register.add_argument('id')
    for field in ('project', 'home', 'source', 'plugin', 'profile', 'purpose'):
        register.add_argument('--' + field, required=True)
    register.add_argument('--reason', help='Why another environment for the same project is needed')
    update = sub.add_parser('update', help='Record changed host identity or handoff state')
    update.add_argument('id')
    update.add_argument('--purpose')
    for field in ('source', 'plugin', 'profile'):
        update.add_argument('--' + field)
    for p in (register, update):
        p.add_argument('--url', type=origin)
        p.add_argument('--pid', type=int)
        p.add_argument('--supervisor', help='Launchd/systemd label; metadata only')
        p.add_argument('--log', help='Private log path; contents/token never stored in registry')
        p.add_argument('--state', choices=('active', 'retained', 'retired'), default='active' if p is register else None)
        p.add_argument('--note', help='Short handoff summary, no secrets')
        p.add_argument('--preferred', action='store_true')
    bind = sub.add_parser('bind', help='Record one case workspace and optional DSH Session; does not create a Session')
    bind.add_argument('id')
    bind.add_argument('--case', required=True)
    bind.add_argument('--workspace', required=True)
    bind.add_argument('--purpose', required=True)
    bind.add_argument('--session')
    args = parser.parse_args()
    registry = Registry(args.db)
    try:
        if args.command == 'list':
            result = [{key: r.get(key) for key in ('id', 'project', 'preferred', 'state', 'purpose', 'url', 'home', 'updated_at')}
                      | {'case_count': len(r['cases'])} for r in registry.list(args.project)]
        elif args.command == 'show':
            result = registry.get(args.id)
        elif args.command == 'check':
            result = check(registry.get(args.id))
        elif args.command == 'bind':
            result = registry.bind(args.id, args.case, args.workspace, args.purpose, args.session)
        else:
            fields = {key: getattr(args, key) for key in
                      ('url', 'pid', 'supervisor', 'log', 'state', 'purpose', 'note')
                      if getattr(args, key) is not None}
            if 'pid' in fields:
                fields['process_fingerprint'] = fingerprint(fields['pid'])
                if fields['process_fingerprint'] is None:
                    raise ValueError('PID is not running; omit it for a stopped deployment')
            if 'log' in fields:
                fields['log'] = path(fields['log'])
            if args.command == 'register':
                for key in ('home', 'source', 'plugin', 'project'):
                    if not Path(getattr(args, key)).expanduser().is_dir():
                        raise ValueError(f'{key} must be an existing directory')
                fields.update(source=path(args.source), plugin=path(args.plugin), profile=args.profile)
                result = registry.register(args.id, args.project, args.home, fields, args.preferred, args.reason)
            else:
                for key in ('source', 'plugin', 'profile'):
                    value = getattr(args, key)
                    if value is not None:
                        if key != 'profile':
                            value = path(value)
                            if not Path(value).is_dir():
                                raise ValueError(f'{key} must be an existing directory')
                        fields[key] = value
                result = registry.update(args.id, fields, args.preferred)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        registry.close()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, sqlite3.Error, OSError, subprocess.SubprocessError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
