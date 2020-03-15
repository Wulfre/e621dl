# Internal Imports
import os
from time import sleep
from timeit import default_timer
from shutil import copyfileobj

# Personal Imports
from e621dl import constants
from e621dl import local

# Vendor Imports
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

def requests_retry_session(
    retries = 5,
    backoff_factor = 0.3,
    status_forcelist = (500, 502, 504),
    session = None,
):
    session = session or requests.Session()
    retry = Retry(
        total = retries,
        read = retries,
        connect = retries,
        backoff_factor = backoff_factor,
        status_forcelist = status_forcelist,
        method_whitelist = frozenset(['GET', 'POST'])
    )
    adapter = HTTPAdapter(max_retries = retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

def delayed_get(url, payload, session):
    # Take time before and after getting the requests response.
    start = default_timer()
    with session.get(url, data = payload) as response:
        elapsed = default_timer() - start

        # If the response took less than 1 second
        # (a hard limit of 2 requests are allowed per second as per the e621 API)
        # Wait for the rest of the 1 second.
        if elapsed < 1:
            sleep(1 - elapsed)

        return response

def get_github_release(session):
    url = 'https://api.github.com/repos/wulfre/e621dl/releases/latest'

    with session.get(url) as response:
        response.raise_for_status()

        return response.json()['tag_name'].strip('v')

def get_posts(search_string, earliest_date, last_id, session):
    url = 'https://e621.net/posts.json'
    payload = {
        'limit': constants.MAX_RESULTS,
        'tags': f"date:>={earliest_date} {search_string}"
    }
    
    if last_id:
        payload.update(tags = f"id:<{last_id} date:>={earliest_date} {search_string}")

    with delayed_get(url, payload, session) as response:
        response.raise_for_status()

        return response.json()

def get_tag_alias(user_tag, session):
    prefix = ''

    if ':' in user_tag:
        print(f"[!] It is not possible to check if {user_tag} is valid.")
        return user_tag

    if user_tag[0] == '~':
        prefix = '~'
        user_tag = user_tag[1:]

    if user_tag[0] == '-':
        prefix = '-'
        user_tag = user_tag[1:]

    url = 'https://e621.net/tag/index.json'
    payload = {'name': user_tag}

    with delayed_get(url, payload, session) as response:
        response.raise_for_status()

        results = response.json()

        if '*' in user_tag and results:
            print(f"[✓] The tag {user_tag} is valid.")
            return user_tag

        for tag in results:
            if user_tag == tag['name']:
                print(f"[✓] The tag {prefix}{user_tag} is valid.")
                return f"{prefix}{user_tag}"

    url = 'https://e621.net/tag_alias/index.json'
    payload = {'approved': 'true', 'query': user_tag}

    with delayed_get(url, payload, session) as response:
        response.raise_for_status()
        results = response.json()

    for tag in results:
        if user_tag == tag['name']:
            url = 'https://e621.net/tag/show.json'
            payload = {'id': tag['alias_id']}

            with delayed_get(url, payload, session) as response:
                response.raise_for_status()
                results = response.json()

                print(f"[✓] The tag {prefix}{user_tag} was changed to {prefix}{results['name']}.")

                return f"{prefix}{results['name']}"

    print(f"[!] The tag {prefix}{user_tag} is spelled incorrectly or does not exist.")
    return ''

def download_post(url, path, session):
    if f".{constants.PARTIAL_DOWNLOAD_EXT}" not in path:
        path += f".{constants.PARTIAL_DOWNLOAD_EXT}"

    # Creates file if it does not exist so that os.path.getsize does not raise an exception.
    try:
        open(path, 'x')
    except FileExistsError:
        pass

    header = {'Range': f"bytes={os.path.getsize(path)}-"}
    with session.get(url, stream = True, headers = header) as response:
        if response.ok:    
            with open(path, 'ab') as outfile:
                copyfileobj(response.raw, outfile)

            os.rename(path, path.replace(f".{constants.PARTIAL_DOWNLOAD_EXT}", ''))

        else:
            print(f"[!] The downoad URL {url} is not available. Error code: {response.status_code}.")

def finish_partial_downloads(session):
    for root, dirs, files in os.walk('downloads/'):
        for file in files:
            if file.endswith(constants.PARTIAL_DOWNLOAD_EXT):
                print(f"[!] Partial download {file} found.")

                path = os.path.join(root, file)
                post_id = int(file.split('.')[0])
                url = get_posts(f"id:{post_id}", 0, post_id + 1, session)['posts'][0]['file']['url']
                download_post(url, path, session)
