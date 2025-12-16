#!/usr/bin/env python3
import asyncio
import argparse
import datetime
import re
import os
import hashlib
from typing import Optional
import httpx

class Colors:
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    CYAN   = "\033[96m"
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    ORANGE = "\033[38;5;208m"

class Level:
    HIGH    = 'high'
    MEDIUM  = 'medium'
    LOW     = 'low'

KEY_USERNAME = 'username'
KEY_USERNAMES_PROBABLES = 'usernames_probables'
KEY_PLATFORM = 'platform'
KEY_URL      = 'url'
KEY_LEVEL    = 'level'
KEY_EMAIL    = 'email'

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"sauron_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")

def log(msg: str):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

def out(msg: str, color: str = "", bold: bool = False):
    style = Colors.BOLD if bold else ""
    print(f"{style}{color}{msg}{Colors.RESET}")
    log(msg)

def out_level_color(level: str):
    if level == Level.HIGH:
        return f'{Colors.BOLD}{Colors.GREEN}{Level.HIGH}{Colors.RESET}'
    elif level == Level.MEDIUM:
        return f'{Colors.BOLD}{Colors.ORANGE}{Level.MEDIUM}{Colors.RESET}'
    else:
        return f'{Colors.BOLD}{Colors.CYAN}{Level.LOW}{Colors.RESET}'

def out_results(results: dict):
    if not results:
        out("No results found", Colors.YELLOW)
        return
    
    for key, val in results.items():
        if not val:
            out("No results found", Colors.YELLOW)
            continue
        out(f"\n{Colors.CYAN}[{key.upper()}]{Colors.RESET}  Found {len(val)} items!\n", bold=True)
        
        if key == KEY_USERNAME or key == KEY_USERNAMES_PROBABLES:
            if val:  
                
                platform_width = max(len(v[KEY_PLATFORM]) for v in val) + 2 
                level_width = 12  
                url_width = 40    

                # Header
                print(f"{'Platform'.ljust(platform_width)}  {'Probability'.ljust(level_width)}  URL")
                print(f"{'-'*platform_width} {'-'*level_width} {'-'*url_width}")

                # Rows
                for v in val:
                    platform = v[KEY_PLATFORM].capitalize().ljust(platform_width)
                    level_color = out_level_color(v[KEY_LEVEL]).ljust(22 + len(Colors.RESET))  # ajuste la couleur
                    url = v[KEY_URL]
                    print(f"{platform}   {level_color} {Colors.BLUE}{url}{Colors.RESET}")
        
# ======= UTIL =======
def derive_usernames(email: str) -> list[str]:
    local = email.split("@")[0]

    candidates = [
        local,
        local.replace(".", ""),
        local.replace("_", ""),
    ]

    return list(dict.fromkeys(candidates))

def generate_username(firstname: str, lastname: str):
    return f"{firstname}{lastname}".lower()

    
async def check_github(username: str) -> dict:
    url = f"https://github.com/{username}"

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.get(url)
            if r.status_code == 200:
                return {
                    "found": True,
                    "platform": "github",
                    "username": username,
                    "url": url,
                    "level": Level.HIGH 
                }
        except Exception:
            pass

    return None

async def check_reddit(username: str) -> dict:
    url = f"https://www.reddit.com/user/{username}/about.json"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(url, headers=headers)

        if r.status_code == 404:
            return None

        data = r.json()

        if "error" in data:
            return None

        return {
            "found": True,
            "platform": "reddit",
            "username": username,
            "url": f"https://www.reddit.com/user/{username}",
            "level": Level.HIGH
        }

    except Exception as e:
        return None
      
async def check_gravatar(email: str) -> dict | None:
    email = email.strip().lower()
    email_hash = hashlib.md5(email.encode()).hexdigest()
    url = f"https://www.gravatar.com/avatar/{email_hash}?d=404"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)

        if r.status_code == 200:
            return {
                "found": True,
                "platform": "gravatar",
                "email": email,
                "url": url
            }

    except Exception:
        pass

    return None

async def check_linkedin(username: str) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    profile_url = f"https://www.linkedin.com/in/{username}/"
    search_url  = f"https://www.linkedin.com/search/results/people/?keywords={username}&origin=GLOBAL_SEARCH_HEADER"

    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        try:
            r = await client.get(profile_url, headers=headers)
            if r.status_code == 200 and "linkedin.com/in/" in str(r.url):
                return {
                    "found": True,
                    "platform": "linkedin",
                    "username": username,
                    "url": str(r.url),
                    "level": Level.HIGH
                }
        except Exception:
            pass

        # 2) Try search
        try:
            r = await client.get(search_url, headers=headers)
            if r.status_code == 200 and "search" in r.text.lower():
                return {
                    "found": True,
                    "platform": "linkedin",
                    "username": username,
                    "url": search_url,
                    "level": Level.LOW
                }
        except Exception:
            pass

    return None

async def check_hibp(email: str, api_key: str) -> dict | None:
    url = f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}"
    headers = {"hibp-api-key": api_key, "User-Agent": "OSINT-Scanner"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=headers)

        if r.status_code == 200:
            return {
                "found": True,
                "platform": "HIBP",
                "email": email,
                "url": f"https://haveibeenpwned.com/account/{email}",
                "level": Level.HIGH
            }
        elif r.status_code == 404:
            return None
    except Exception:
        pass
    return None

async def check_x(username: str) -> dict | None:
    url = f"https://x.com/{username}"  # Formerly twitter
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(url, headers=headers)
            if r.status_code == 200:
                return {
                    "found": True,
                    "platform": "X",
                    "username": username,
                    "url": url,
                    "level": Level.HIGH
                }
    except Exception:
        pass
    return None

async def check_twitch(username: str) -> dict | None:
    url = f"https://www.twitch.tv/{username}"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(url, headers=headers)

        if r.status_code != 200:
            return None

        # Vérifier le titre exact
        title_match = re.search(rf'<title>\s*{re.escape(username)}\s*-\s*Twitch\s*</title>', r.text, re.IGNORECASE)
        if title_match:
            return {
                "found": True,
                "platform": "twitch",
                "username": username,
                "url": url,
                "level": Level.HIGH
            }

    except Exception:
        return None

async def check_mastodon(username: str, instance: str = "mastodon.social") -> dict | None:
    url = f"https://{instance}/@{username}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
        if r.status_code == 200:
            return {
                "found": True,
                "platform": "mastodon",
                "username": username,
                "url": url,
                "level": Level.HIGH
            }
    except Exception:
        pass
    return None

async def check_gitlab(username: str) -> dict | None:
    url = f"https://gitlab.com/{username}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
        if r.status_code == 200:
            return {
                "found": True,
                "platform": "gitLab",
                "username": username,
                "url": url,
                "level": Level.HIGH
            }
    except Exception:
        pass
    return None

async def check_keybase(username: str) -> dict | None:
    url = f"https://keybase.io/{username}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
        if r.status_code == 200:
            return {
                "found": True,
                "platform": "Keybase",
                "username": username,
                "url": url,
                "level": Level.HIGH
            }
    except Exception:
        pass
    return None

async def check_medium(username: str) -> dict | None:
    url = f"https://medium.com/@{username}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
        if r.status_code == 200:
            return {
                "found": True,
                "platform": "medium",
                "username": username,
                "url": url,
                "level": Level.HIGH
            }
    except Exception:
        pass
    return None

async def check_devto(username: str) -> dict | None:
    url = f"https://dev.to/{username}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
        if r.status_code == 200:
            return {
                "found": True,
                "platform": "dev.to",
                "username": username,
                "url": url,
                "level": Level.HIGH
            }
    except Exception:
        pass
    return None

async def check_youtube(username: str) -> dict | None:
    url = f"https://www.youtube.com/@{username}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=headers)
        if r.status_code == 200:
            return {
                "found": True,
                "platform": "youtube",
                "username": username,
                "url": url,
                "level": Level.HIGH
            }
    except Exception:
        pass
    return None

async def check_tryhackme(username: str) -> dict | None:
    url = f"https://tryhackme.com/p/{username}"
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    NEGATIVE_MARKERS = [
        "nothing to see here",
        "this page doesn't exist",
        "page not found",
        "404"
    ]

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(url, headers=headers)

        if r.status_code != 200:
            return None

        text = r.text.lower()
        print(r.text)

        for marker in NEGATIVE_MARKERS:
            if marker in text:
                return None

        return {
            "found": True,
            "platform": "tryhackme",
            "username": username,
            "url": url,
            "level": Level.LOW
        }

    except Exception:
        return None

async def check_instagram(username: str) -> dict | None:
    url = f"https://www.instagram.com/{username}/"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=headers)
        if r.status_code == 200:
            return {
                "found": True,
                "platform": "instagram",
                "username": username,
                "url": url,
                "level": Level.HIGH
            }
    except Exception:
        pass
    return None

async def check_discord(username: str) -> dict | None:
    """
    Vérifie si un utilisateur Discord existe via l'URL publique de profil (si disponible).
    """
    url = f"https://discord.com/users/{username}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=headers)
        if r.status_code == 200:
            return {
                "found": True,
                "platform": "discord",
                "username": username,
                "url": url,
                "level": Level.HIGH
            }
    except Exception:
        pass
    return None


async def check_hibp(email: str, api_key: str) -> dict | None:
    """
    Check if email has been pwned using HaveIBeenPwned API.
    Requires an API key from https://haveibeenpwned.com/API/Key
    """
    url = f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}"
    headers = {
        "hibp-api-key": api_key,
        "user-agent": "SauronEye/1.0"
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=headers)
        if r.status_code == 200:
            return {
                "found": True,
                "platform": "hibp",
                "email": email,
                "breaches": r.json()  # liste des breaches
            }
        elif r.status_code == 404:
            return None
    except Exception as e:
        print(f"HIBP error: {e}")
    return None


# ======= Checkers ===========

async def check_username(username: str) -> dict:
    tasks = [
        check_github(username),
        check_reddit(username),
        check_linkedin(username),
        check_x(username),
        check_instagram(username),
        check_youtube(username),
        check_twitch(username),
        check_discord(username),
        check_tryhackme(username),
        check_mastodon(username),
        check_gitlab(username),
        check_keybase(username),
        check_medium(username),
        check_devto(username)
    ]
    
    results = await asyncio.gather(*tasks)

    return [r for r in results if r]

async def check_email(email: str, hibp_api_key: str = None) -> list | None:
    tasks = [check_gravatar(email)]
    if hibp_api_key:
        tasks.append(check_hibp(email, hibp_api_key))

    results = await asyncio.gather(*tasks)

    # Filter out None
    found = [r for r in results if r is not None]
    return found if found else None

async def check_all(username: Optional[str]=None, email: Optional[str]=None, firstname: Optional[str]=None, lastname: Optional[str]=None):
    results = {}
    tasks = {}

    if firstname and lastname:
        username = generate_username(firstname, lastname)
        
    if username:
        username = username.replace("-", "").replace("_", "")
        tasks["username"] = check_username(username)

    if email:
        tasks["email"] = check_email(email)
        
        if not username:
            usernames = derive_usernames(email)

            for u in usernames:
                tasks["usernames_probables"] = check_username(u)


    # for u in usernames:

    if tasks:
        completed = await asyncio.gather(*tasks.values())
        results = dict(zip(tasks.keys(), completed))

    return results


# ======= MAIN ENTRY =======
async def run_scan(args):
    out("\nSAURON EYE STARTED\n", Colors.BOLD)

    results = await check_all(args.username, args.email, args.firstname, args.lastname)
    out_results(results)

    out(f"\nLog saved to {LOG_FILE}", Colors.YELLOW)
    out("\nSAURON EYE DONE\n", Colors.BOLD)

def main():
    parser = argparse.ArgumentParser(description="Sauron Eye OSINT Scanner")
    parser.add_argument("--username", type=str, help="Username to scan")
    parser.add_argument("--email", type=str, help="Email to scan")
    parser.add_argument("--firstname", type=str, help="Firstname for LinkedIn")
    parser.add_argument("--lastname", type=str, help="Lastname for LinkedIn")
    args = parser.parse_args()

    asyncio.run(run_scan(args))

if __name__ == "__main__":
    main()
