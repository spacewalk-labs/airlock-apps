#!/usr/bin/env python3
"""Non-destructively import legacy dev-monitor DB/spool into the Airlock state path."""
import os
import sqlite3
import stat
import sys
from urllib.parse import quote


def is_real_directory(path):
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except FileNotFoundError:
        return False


def ensure_real_directory(path):
    if os.path.lexists(path):
        if not is_real_directory(path):
            raise RuntimeError(f'refusing non-directory state path: {path}')
        os.chmod(path, 0o700)
        return
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, mode=0o700, exist_ok=True)
    os.mkdir(path, 0o700)


def copy_regular_exclusive(source, destination):
    """Copy one regular file without following source symlinks or replacing destination."""
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0)
    try:
        source_fd = os.open(source, flags)
    except (FileNotFoundError, OSError):
        return 'absent'
    try:
        if not stat.S_ISREG(os.fstat(source_fd).st_mode):
            return 'unsafe'
        try:
            destination_fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return 'exists'
        try:
            with os.fdopen(source_fd, 'rb', closefd=False) as src, \
                    os.fdopen(destination_fd, 'wb') as dst:
                while True:
                    block = src.read(1024 * 1024)
                    if not block:
                        break
                    dst.write(block)
                dst.flush()
                os.fsync(dst.fileno())
        except Exception:
            try:
                os.unlink(destination)
            except FileNotFoundError:
                pass
            raise
        return 'copied'
    finally:
        os.close(source_fd)


def backup_sqlite_exclusive(source, destination):
    """Create a consistent SQLite snapshot, including committed WAL content."""
    try:
        source_stat = os.lstat(source)
    except FileNotFoundError:
        return 'absent'
    if not stat.S_ISREG(source_stat.st_mode):
        return 'unsafe'
    if os.path.lexists(destination):
        if not stat.S_ISREG(os.lstat(destination).st_mode):
            raise RuntimeError(f'refusing non-regular database path: {destination}')
        return 'exists'
    try:
        destination_fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if not stat.S_ISREG(os.lstat(destination).st_mode):
            raise RuntimeError(f'refusing non-regular database path: {destination}')
        return 'exists'
    os.close(destination_fd)
    source_db = destination_db = None
    try:
        uri = 'file:%s?mode=ro' % quote(os.path.abspath(source), safe='/')
        source_db = sqlite3.connect(uri, uri=True, timeout=5)
        destination_db = sqlite3.connect(destination)
        source_db.backup(destination_db)
        destination_db.commit()
        destination_db.close()
        destination_db = None
        source_db.close()
        source_db = None
        fd = os.open(destination, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return 'copied'
    except Exception:
        if destination_db is not None:
            destination_db.close()
        if source_db is not None:
            source_db.close()
        try:
            os.unlink(destination)
        except FileNotFoundError:
            pass
        raise


def migrate(legacy, canonical):
    ensure_real_directory(canonical)
    spool = os.path.join(canonical, 'spool')
    ensure_real_directory(spool)
    spool_new = os.path.join(canonical, 'spool', 'new')
    ensure_real_directory(spool_new)
    results = {'db': backup_sqlite_exclusive(
        os.path.join(legacy, 'messages.db'), os.path.join(canonical, 'messages.db')),
        'spool_copied': 0, 'spool_skipped': 0}
    for queue in ('new', 'processing'):
        source_dir = os.path.join(legacy, 'spool', queue)
        if not is_real_directory(source_dir):
            continue
        try:
            names = sorted(os.listdir(source_dir))
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            continue
        for name in names:
            if '/' in name or name in ('.', '..'):
                results['spool_skipped'] += 1
                continue
            status = copy_regular_exclusive(
                os.path.join(source_dir, name), os.path.join(spool_new, name))
            if status == 'copied':
                results['spool_copied'] += 1
            else:
                results['spool_skipped'] += 1
    return results


def main(argv):
    if len(argv) != 3:
        raise SystemExit(f'usage: {argv[0]} LEGACY_STATE CANONICAL_STATE')
    result = migrate(os.path.abspath(argv[1]), os.path.abspath(argv[2]))
    print('legacy import: db=%s spool_copied=%d spool_skipped=%d' % (
        result['db'], result['spool_copied'], result['spool_skipped']))


if __name__ == '__main__':
    main(sys.argv)
