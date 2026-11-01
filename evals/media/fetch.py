#!/usr/bin/env python3
"""Fetch or import pinned public evaluation media without putting media in the repository.

  python evals/media/fetch.py CACHE [--from-corpus DIR] [--fetch] [SOURCE ...]

Verify SHA-256 before use. A local corpus is read-only. Network access is opt-in.
No transcript or licence claim is verified by a matching hash.
Exit 0 when selected sources are present, 1 on a mismatch, 2 on an operational error.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path


HERE = Path(__file__).resolve().parent
APPROVED_DOMAINS = ('archive.org', 'gutenberg.org', 'nasa.gov', 'incompetech.com', 'dotsrc.org')


def approved_url(url):
    """Allow only HTTPS source hosts or subdomains already represented in the corpus."""
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or '').lower()
    return parsed.scheme == 'https' and any(host == domain or host.endswith('.' + domain)
                                            for domain in APPROVED_DOMAINS)


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Reject a redirect before contacting any unlisted host."""

    def redirect_request(self, request, fp, code, message, headers, newurl):
        """Follow only approved HTTPS destinations."""
        if not approved_url(newurl):
            raise ValueError(f'redirect to unapproved URL: {newurl}')
        return super().redirect_request(request, fp, code, message, headers, newurl)


def digest(path):
    """Hash a file without reading it all into memory."""
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def verified_copy(source, target, expected):
    """Copy to a temporary file and publish only after verifying the bytes."""
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix='.download-', dir=str(target.parent))
    os.close(handle)
    temporary = Path(name)
    try:
        shutil.copyfile(source, temporary)
        actual = digest(temporary)
        if actual != expected:
            raise ValueError(f'{target.name}: expected {expected}, got {actual}')
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def download(url, target, expected):
    """Stream one pinned URL into a temporary local file and verify it."""
    if not approved_url(url):
        raise ValueError(f'unapproved source URL: {url}')
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix='.download-', dir=str(target.parent))
    os.close(handle)
    temporary = Path(name)
    try:
        opener = urllib.request.build_opener(SafeRedirect())
        with opener.open(url, timeout=60) as response, temporary.open('wb') as out:
            shutil.copyfileobj(response, out, length=1024 * 1024)
        actual = digest(temporary)
        if actual != expected:
            raise ValueError(f'{target.name}: expected {expected}, got {actual}')
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    """Check or populate the cache with a selected subset of the manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cache', type=Path)
    parser.add_argument('--from-corpus', type=Path)
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('source', nargs='*')
    args = parser.parse_args()
    manifest = json.loads((HERE / 'sources.json').read_text(encoding='utf-8'))
    sources = {row['file']: row for row in manifest['sources']}
    selected = args.source or sorted(sources)
    unknown = set(selected) - sources.keys()
    if unknown:
        parser.error('unknown sources: ' + ', '.join(sorted(unknown)))
    try:
        for name in selected:
            source = sources[name]
            target = (args.cache / name).resolve()
            if not target.is_relative_to(args.cache.resolve()):
                raise ValueError(f'cache path escapes its root: {name}')
            if target.is_file():
                actual = digest(target)
                if actual == source['sha256']:
                    print(f'verified {name}')
                    continue
                if not args.from_corpus and not args.fetch:
                    raise ValueError(f'{name}: expected {source["sha256"]}, got {actual}')
            if args.from_corpus and (args.from_corpus / name).is_file():
                verified_copy(args.from_corpus / name, target, source['sha256'])
            elif args.fetch:
                download(source['source_url'], target, source['sha256'])
            else:
                raise FileNotFoundError(f'{name}: no verified cache or source; use --from-corpus or --fetch')
            print(f'verified {name}')
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, TimeoutError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
