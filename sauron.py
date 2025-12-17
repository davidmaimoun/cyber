#!/usr/bin/env python3
import asyncio
import argparse
import json
import re
import datetime
import os
from collections import Counter, defaultdict
import httpx

# ================= COLORS & LEVELS =================
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

# ================= LOGGING =================
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"sauron_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt")

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
                level_width = max(len(v[KEY_LEVEL]) for v in val) + 2  # dynamique selon le texte
                url_width = 40

                # Header
                print(f"{ 'Platform'.ljust(platform_width)}  {'Level'.ljust(level_width)}  URL")
                print(f"{'-'*platform_width}  {'-'*level_width}  {'-'*url_width}")

                # Rows
                for v in val:
                    platform = v[KEY_PLATFORM].capitalize().ljust(platform_width)
                    level_text = v[KEY_LEVEL].ljust(level_width)
                    # Appliquer couleur sans décaler
                    if v[KEY_LEVEL] == Level.HIGH:
                        level_color = f"{Colors.BOLD}{Colors.GREEN}{level_text}{Colors.RESET}"
                    elif v[KEY_LEVEL] == Level.MEDIUM:
                        level_color = f"{Colors.BOLD}{Colors.ORANGE}{level_text}{Colors.RESET}"
                    else:
                        level_color = f"{Colors.BOLD}{Colors.CYAN}{level_text}{Colors.RESET}"

                    url = v[KEY_URL]
                    print(f"{platform}   {level_color}  {Colors.BLUE}{url}{Colors.RESET}")


# ================= UTILITIES =================
def derive_usernames(email: str):
    local = email.split("@")[0]
    candidates = [
        local,
        local.replace(".", ""),
        local.replace("_", ""),
    ]
    return list(dict.fromkeys(candidates))

def generate_username(firstname: str, lastname: str):
    return f"{firstname}{lastname}".lower()


# ================= LOAD SITES =================
def load_sites():
    with open("data.json", "r", encoding="utf-8") as f:
        return json.load(f)


# ================= CHECK ENGINE =================
async def check_site(site_name, site_cfg, username):
    if site_cfg.get("force_lowercase"):
        username = username.lower()

    # URL pour affichage et test
    url_display = site_cfg["url"].format(username)
    url_probe = site_cfg.get("urlProbe", site_cfg["url"]).format(username)

    response_type = site_cfg.get("responseType", "status_code")
    response_error = site_cfg.get("responseError")
    response_success = site_cfg.get("responseSuccess")
    regex_check = site_cfg.get("regexCheck")
    
    # Vérification regex si définie
    if regex_check and not re.match(regex_check, username):
        return None
    

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(url_probe)
         

        # ===== STATUS CODE =====
        if response_type == "status_code":
            valid_codes = site_cfg.get("validStatus", [200])
            if isinstance(valid_codes, int):
                valid_codes = [valid_codes]
            if r.status_code not in valid_codes:
                return None

        # ===== MESSAGE DANS LE BODY =====
        elif response_type == "message":
            error_msg = site_cfg.get("responseError", "")
            if error_msg in r.text:
                return None

        # ===== JSON =====
        elif response_type == "json":
            try:
                data = r.json()
            except Exception:
                return None

            # Vérifie succès ou erreur
            if response_error:
                match_error = all(data.get(k) == v for k, v in response_error.items())
                if match_error:
                    return None
            if response_success:
                match_success = all(data.get(k) == v for k, v in response_success.items())
                if not match_success:
                    return None

        # ===== HTML CHECK =====
        elif response_type == "html":
            html_check = site_cfg.get("htmlCheck", "").format(username)
            if html_check.lower() not in r.text.lower():
                return None

        # ===== DEFAULT =====
        else:
            if r.status_code != 200:
                return None

        # Niveau de confiance
        conf = site_cfg.get("confidence", 50)
        level = Level.HIGH if conf >= 90 else Level.MEDIUM if conf >= 70 else Level.LOW

        return {
            "platform": site_name,
            "username": username,
            "url": url_display,  # URL pour navigation réelle
            "level": level,
            "confidence": conf,
            "tags": site_cfg.get("tags", []),
        }

    except Exception:
        return None

# ================= USERNAME SCAN =================
async def scan_username(username):
    sites = load_sites()
    tasks = [check_site(site, site_config, username) for site, site_config in sites.items()]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r]


# ================= USERNAME GENERATION =================
async def generate_and_scan(username=None, email=None, firstname=None, lastname=None):
    results = {}
    if username:
        results["username"] = await scan_username(username)
    else:
        generated = []
        if firstname and lastname:
            generated.append(generate_username(firstname, lastname))
        if email:
            generated.extend(derive_usernames(email))
        results["usernames_probables"] = []
        for u in generated:
            res = await scan_username(u)
            results["usernames_probables"].extend(res)
    return results

# ================= SCORING & PROFILING =================
def compute_score(results):
    if not results:
        return 0
    base = sum(r["confidence"] for r in results) / len(results)
    diversity = len({r["platform"] for r in results})
    return min(100, int(base + diversity * 2))

def profiling(results):
    tag_count = Counter()
    for r in results:
        tag_count.update(r["tags"])
    if not tag_count:
        return {"profile": "unknown", "details": {}}
    dominant = tag_count.most_common(1)[0][0]
    return {"profile": dominant, "details": dict(tag_count)}

def correlation(results):
    platforms = [r["platform"] for r in results]
    tags = defaultdict(list)
    for r in results:
        for t in r["tags"]:
            tags[t].append(r["platform"])
    return {"platforms": platforms, "tag_map": dict(tags)}


async def run_scan(username=None, email=None, firstname=None, lastname=None):
    out("\n👁️ SAURON EYE STARTED\n", Colors.BOLD)
    results = await generate_and_scan(username=username, email=email, firstname=firstname, lastname=lastname)
    
    out_results(results)

    # Combine all results for analysis
    all_res = []
    for k in results:
        all_res.extend(results[k])

    score = compute_score(all_res)
    profile = profiling(all_res)
    corr = correlation(all_res)

    out("\n[Profiling]", Colors.CYAN, bold=True)
    out(f"{Colors.BLUE}For the target: {username}")
    out(f"Confidence score : {score}/100", Colors.CYAN)
    out(f"Dominant profile : {profile['profile']}", Colors.CYAN)
    out("Interests:", Colors.CYAN)
    for k, v in profile["details"].items():
        out(f"  - {k}: {v}", Colors.YELLOW)

    out("\nPlatforms: " + ", ".join(corr["platforms"]), Colors.BLUE)
    log(json.dumps({
        "username": username,
        "email": email,
        "results": all_res,
        "score": score,
        "profile": profile,
        "correlation": corr
    }, indent=2))
    out("\n👁️ SAURON EYE DONE\n", Colors.BOLD)

# ================= ARGUMENTS =================
def main():
    parser = argparse.ArgumentParser(description="Sauron Eye OSINT Scanner")
    parser.add_argument("--username", type=str, help="Username to scan")
    parser.add_argument("--email", type=str, help="Email to scan")
    parser.add_argument("--firstname", type=str, help="Firstname")
    parser.add_argument("--lastname", type=str, help="Lastname")
    args = parser.parse_args()

    asyncio.run(run_scan(username=args.username, email=args.email, firstname=args.firstname, lastname=args.lastname))

if __name__ == "__main__":
    main()
