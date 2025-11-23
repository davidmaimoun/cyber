#!/usr/bin/env python3
import argparse
import requests
import csv
import urllib3
import sys
import re
from urllib.parse import urljoin
import re




class Colors:
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    CYAN   = "\033[96m"
    RESET  = "\033[0m"
    BOLD   = "\033[1m"


STATIC_DIRS = [
    "static",
    "assets",
    "resources",
    "res",
    "public",
    "content",
    "files",
    "media",
    "img",
    "images",
    "js",
    "css",
    "fonts",
    "scripts",
    "lib",
    "dist",
    "build",
    "_next",       # Next.js
    "wp-content",  # WordPress
    "wp-includes", # WordPress
    "vendor",
    "client",
    "themes",
    "uploads",
    "data",
]

DELIMITERS = [
    "!", '"', "#", "$", "%", "&", "'", "(", ")", "*", "+", ",", "-", ".", "/", ":", ";",
    "<", "=", ">", "?", "@", "[", "\\", "]", "^", "_", "`", "{", "|", "}", "~",
    "%21","%22","%23","%24","%25","%26","%27","%28","%29","%2A","%2B","%2C","%2D",
    "%2E","%2F","%3A","%3B","%3C","%3D","%3E","%3F","%40","%5B","%5C","%5D",
    "%5E","%5F","%60","%7B","%7C","%7D","%7E",
]


def fetch(url, cookies=None):
    try:
        r = requests.get(url, cookies=cookies, timeout=7, allow_redirects=True)
        if r.status_code >= 500:
            print(f"{Colors.RED}[ERROR] Server returned {r.status_code}. Stopping.{Colors.RESET}")
            sys.exit(1)
        return r
    except Exception as e:
        print(f"{Colors.RED}[ERROR] Request failed: {e}{Colors.RESET}")
        sys.exit(1)

def fetch_raw_headers(url):
    http = urllib3.PoolManager()
    resp = http.request("GET", url, redirect=False)
    return resp

def clean(resp_data):
    try:
        text = resp_data.decode("utf-8", errors="ignore")
    except:
        text = str(resp_data)

    text = re.sub(r"<script.*?</script>", "", text, flags=re.DOTALL)
    text = re.sub(r"value=['\"][A-Za-z0-9-_]{20,}['\"]", "", text)
    text = re.sub(r"\d{4}-\d{2}-\d{2}", "", text)
    text = re.sub(r"\d{10,13}", "", text)
    text = re.sub(r"[A-Za-z0-9]{32,}", "", text)

    return text.strip()


def responses_similar(base, modified):
    if base.status != modified.status:
        return False

    blen = len(base.data)
    mlen = len(modified.data)
    if abs(blen - mlen) > blen * 0.10:
        return False

    base_clean = clean(base.data)
    mod_clean = clean(modified.data)

    if base_clean[:200] == mod_clean[:200]:
        return True
    if base_clean[-200:] == mod_clean[-200:]:
        return True

    return False
def is_cached(headers):
    cache_indicators = [
        "X-Cache", "CF-Cache-Status", "Age", "X-Proxy-Cache"
    ]
    for key in cache_indicators:
        if key in headers:
            v = headers.get(key, "")
            if any(w in v.lower() for w in ["miss", "hit", "cached", "refresh", "revalidate", "stale"]):
                return True
    return False

def delimiter_match(base, modified):
    return (
        modified.status_code in (200, 301, 302) and
        len(modified.text) >= len(base.text) * 0.5
    )


def test_path_mapping_dis(url, base_resp):
    print(f"{Colors.BLUE}{Colors.BOLD}\n[1] Detecting PATH MAPPING discrepancies...{Colors.RESET}")

    # Extract endpoint and parent paths
    endpoint = url.rstrip("/").split("/")[-1]

    # 1) Test PATH ABSTRACTION: /my-account/abc
    test_url_1 = f"{url.rstrip('/')}/abc"
    print(f"{Colors.BLUE}→ Testing origin path abstraction: {test_url_1}{Colors.RESET}")
    
    modified_resp_1 = fetch_raw_headers(test_url_1)

    if responses_similar(base_resp, modified_resp_1):
        print(f"{Colors.GREEN}  ✔ Origin abstracts /{endpoint}/abc → /{endpoint}{Colors.RESET}")
    else:
        print(f"{Colors.RED}    ✘ Origin DOES NOT abstract path. No mapping discrepancy here.{Colors.RESET}")
        return False

    # 2) Test CACHE BEHAVIOR with static extension: /my-account/abc.js
    modified_url_for_cache = f"{url.rstrip('/')}/abc.js"
    modified_resp_for_cache = fetch_raw_headers(modified_url_for_cache)

    print(f"{Colors.BLUE}→ Testing cache behavior for static extension: {modified_url_for_cache}{Colors.RESET}")

    cached_before = is_cached(modified_resp_for_cache.headers)

    if cached_before:
        print(f"{Colors.GREEN}  ✔ Response already cached on first request (rare but possible){Colors.RESET}")
    else:
        print(f"{Colors.YELLOW} ↳ Not cached yet (X-Cache: miss). Retesting...{Colors.RESET}")

    # 3) Re-request to confirm HIT
    resp3 = fetch_raw_headers(modified_url_for_cache)
    cached_after = is_cached(resp3.headers)

    if cached_after:
        print(f"{Colors.GREEN}  ✔ Cache rule detected for *.js extension !{Colors.RESET}")
        print(f"{Colors.CYAN}→ The cache interprets the path literally as /{endpoint}/abc.js{Colors.RESET}")
        print(f"{Colors.GREEN}→ PATH MAPPING DISCREPANCY CONFIRMED 🔥{Colors.RESET}")

        return {
            "success": True,
            "payload": modified_url_for_cache,
            "exploit_example": f"/{endpoint}/wcd.js"
        }

    else:
        print(f"{Colors.RED}✘ No cache hit after second request. No mapping discrepancy.{Colors.RESET}")
        return False

def test_delimiters_dis(url, base_resp):
    delim_hits = []
    cache_hits_url = []
    
    print(f"\n{Colors.BLUE}{Colors.BOLD}[2] Testing delimiters...{Colors.RESET}")
    
    for d in DELIMITERS:
        test_url = f"{url.rstrip('/')}{d}test"
        modified_resp = fetch_raw_headers(test_url)

        if not responses_similar(base_resp, modified_resp):
            continue
                
        cached = is_cached(modified_resp.headers)
        print(test_url)
        print(modified_resp.headers)
        if cached:
            cache_hits_url.append[d]

        delim_hits.append(d)

    
    return delim_hits, cache_hits_url
        
def test_origin_normalization_dis(url, base_resp, cookies=None):
    print(f"\n{Colors.BLUE}{Colors.BOLD}[3] Testing ORIGIN normalization{Colors.RESET}\n")

    normals = ["../", "..%2f", "%2e%2e%2f"]
    dirs_cache_found = []
    normals_found    = []

    endpoint = url.rstrip("/").split("/")[-1]
    parent = url.rstrip("/").rsplit("/", 1)[0]

    for n in normals:
        test_url = f"{parent}/aaa/{n}{endpoint}"
        modified_resp = fetch_raw_headers(test_url)
       
        if not responses_similar(base_resp, modified_resp):
            continue
        
        normals_found.append(n)

        print(f"{Colors.GREEN}[+] Origin NORMALIZATION detected with payload: {n}{Colors.RESET}")
        print(f"{Colors.CYAN}    → Origin rewrote {test_url} to /{endpoint}{Colors.RESET}")
        
        cached = is_cached(modified_resp.headers)

        if not cached:
            print(f"{Colors.RED}    ✘ But no cache found")
            print(f"{Colors.BLUE}   ⮡ Checking static dir for cache...{Colors.RESET}")
            
            for sd in STATIC_DIRS:
                test_url = f"{url.rsplit('/',1)[0]}/{sd}/{n}{endpoint}"
                modified_resp = fetch_raw_headers(test_url)
            
                cached = is_cached(modified_resp.headers)
                if cached:
                    print(f"{Colors.GREEN}{Colors.BOLD}    ✔ Cache found! Try this payload: {test_url}{Colors.RESET}")
                    dirs_cache_found.append(test_url)
            
            if not dirs_cache_found: 
                print(f"{Colors.RED}     → No static dir work{Colors.RESET}")


    return normals_found, dirs_cache_found

    # print(f"{Colors.RED}[-] No ORIGIN normalization.{Colors.RESET}")
    # return False



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Minimal Path Mapping Discrepancy Fuzzer (Burp-free)")
    parser.add_argument( "-t", "--target", required=True, help="Target base URL, e.g. http://example.com/item/123")
    
    args = parser.parse_args()

    target = args.target
    cookies = None

    if "-c" in sys.argv:
        idx = sys.argv.index("-c")
        cookies = dict([sys.argv[idx+1].split("=", 1)])

    base_url = target.rstrip("/")
    base_resp = fetch_raw_headers(base_url)

    # path_mapping_result = test_path_mapping_dis(base_url, base_resp)

    # if path_mapping_result['success']:
    #     exit()

    delimiters_hits, cache_hits_url = test_delimiters_dis(target, base_resp)

    if delimiters_hits and cache_hits_url:
        color = Colors.GREEN
        print(color + f"[+] Delimiter match and cache found!")
        for c in cache_hits_url:
            print(color + "     -> Try this payload: ", cache_hits_url)
        
    print(Colors.YELLOW + f"[+] Delimiter match: {{{', '.join(delimiters_hits)}}} but no cache found" + Colors.RESET)

    # test_origin_normalization_dis(target, base_resp)
    

