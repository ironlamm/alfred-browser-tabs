import collections
import hashlib
import json
import logging
import pathlib
import re
import subprocess
import sys
import time
import urllib

import lockfile

ALFRED_CACHE_DIR = pathlib.Path('~/Library/Caches/com.runningwithcrayons.Alfred/Workflow Data/').expanduser()
FAVICON_CACHE_DIR = ALFRED_CACHE_DIR / 'slamm.browser.tabs'
CURL_LOG_PATH = FAVICON_CACHE_DIR / 'curl.log'
LOCK_PATH = FAVICON_CACHE_DIR / 'lock.pid'
MAX_RUN_TIME_SEC = 0.3

FAVICON_URL_FORMAT = "https://t2.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url={url}&size={size}"
FAVICON_SIZE = 32
SCRIPT_DIR = pathlib.Path(__file__).parent.resolve()
FAVICON_KEY_URL_RE = re.compile(r'[?#].*')  # no query/hash
FAVICON_FILE_RE = re.compile(r'\w+://(?:www\.)?([^?#]+).*')  # no protocol or query/hash


global logger
logger = logging.getLogger()
def init_logger():
    logger.setLevel(logging.DEBUG)

    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)

    # Create a formatter and set it for the handler
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)

    # Add the handler to the logger
    logger.addHandler(handler)


def get_tabs(browser):
    tabs_run = subprocess.Popen([f'{SCRIPT_DIR}/list-tabs.js', f'{browser}'], stdout=subprocess.PIPE)
    return json.loads(tabs_run.stdout.read())


def get_favicon_url(url, size):
    key_url = FAVICON_KEY_URL_RE.sub('', url)  # no query or hash
    return FAVICON_URL_FORMAT.format(url=key_url, size=size)


def get_favicon_path(url, dir=FAVICON_CACHE_DIR):
    file_url = FAVICON_FILE_RE.sub(r'\1', url)  # no query or hash
    quoted_url = urllib.parse.quote(file_url, safe='')
    hash_object = hashlib.sha256()
    hash_object.update(quoted_url.encode('utf-8'))
    return dir / f'{hash_object.hexdigest()}.png'


class IconDownloader:
    def __init__(self, url_paths, timeout=0.1):
        self.url_paths = url_paths
        self.timeout = timeout
        self.lockfile = lockfile.LockFile(LOCK_PATH)
        self.proc = None

    def download(self):
        unique_path_urls = collections.OrderedDict(self.url_paths)
        needed_path_urls = [(u, p) for u, p in unique_path_urls.items() if not p.exists()]
        if not needed_path_urls:
            logger.debug('No icons to download')
            return
        elif not self.lockfile.acquire():
            logger.debug('Unable to acquire lock')
            return
        curl_in = ['parallel']
        for url, path in needed_path_urls:
            curl_in.append(f'output "{path}"\nurl "{get_favicon_url(url, FAVICON_SIZE)}"')
        self.proc = subprocess.Popen(
            ['nohup', '/usr/bin/curl', '--config', '-'],
            stdin=subprocess.PIPE,
            stdout=CURL_LOG_PATH.open('w'),
            stderr=subprocess.STDOUT,
            text=True)
        logger.debug(f'Downloading {len(needed_path_urls)} icons')
        self.proc.communicate(input='\n'.join(curl_in))
        logger.debug(f'Download will wait for {self.timeout}s')
        self.proc.wait(timeout=self.timeout)

    def is_icon_downloaded(self, icon_path):
        is_downloaded = icon_path.exists()
        if self.proc and self.proc.poll() is None:
            logger.debug('release the lock')
            self.lockfile.release()
            self.proc = None
        return is_downloaded


def main(argv):
    # TODO clean up old files
    start_time = time.monotonic()
    browser = argv[1]
    init_logger()

    if not LOCK_PATH.parent.exists():
        LOCK_PATH.parent.mkdir()

    logger.debug(f'list-tabs "{browser}"')
    logger.debug(f'Icon dir: {FAVICON_CACHE_DIR}')
    tabs = get_tabs(browser)
    logger.debug(f'{time.monotonic() - start_time:.2f}s: Finished getting tabs')
    urls = [t['url'] for t in tabs['items']]
    paths = [get_favicon_path(u) for u in urls]
    timeout = max(0, (MAX_RUN_TIME_SEC - (time.monotonic() - start_time)))
    downloader = IconDownloader(zip(urls, paths), timeout=timeout)
    downloader.download()
    for path, result in zip(paths, tabs['items']):
        if downloader.is_icon_downloaded(path):
            result['icon'] = {'path': str(path)}
    print(json.dumps(tabs))


if __name__ == "__main__":
    main(sys.argv)