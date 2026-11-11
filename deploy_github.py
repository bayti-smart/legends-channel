#!/usr/bin/env python3
"""
One-shot deployment to a NEW PRIVATE GitHub repo using only a GitHub token:
  creates the repo -> uploads the project -> stores your secrets (encrypted, GitHub-style) -> optionally starts a test run and reports the result.

  export GH_TOKEN=...                       # classic token with the "repo" and "workflow" boxes ticked
  python deploy_github.py --repo legends-channel \
      --secret GEMINI_API_KEY=... --secret YT_CLIENT_ID=... --secret YT_CLIENT_SECRET=... --secret YT_REFRESH_TOKEN=... \
      --secret TELEGRAM_BOT_TOKEN=... --secret TELEGRAM_CHAT_ID=... --var YT_PRIVACY=private --run

Needs:  pip install requests pynacl      (only on the machine that runs this script)
Secret values are never printed.
"""
import argparse, base64, io, os, sys, time, zipfile
from pathlib import Path
from urllib.parse import quote

import requests

API = os.environ.get("GH_API", "https://api.github.com")
HERE = Path(__file__).resolve().parent
SKIP_DIRS = {"__pycache__", ".work", "out", "models", ".tts_cache", ".image_cache", "fonts", ".git"}
SKIP_FILES = {"reel.yml"}                 # the old manual stickman workflow
SKIP_SUFFIX = {".mp4", ".zip", ".pyc", ".wav"}


class GH:
    def __init__(self, token):
        self.s = requests.Session()
        self.s.headers.update({"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "legend-deployer"})

    def call(self, method, path, ok=(200, 201, 204), **kw):
        r = self.s.request(method, API + path, timeout=120, **kw)
        if r.status_code not in ok:
            raise SystemExit(f"GitHub {method} {path} -> {r.status_code}: {r.text[:300]}")
        return r


def files_to_upload():
    for p in sorted(HERE.rglob("*")):
        rel = p.relative_to(HERE)
        if p.is_dir() or any(part in SKIP_DIRS for part in rel.parts) or p.name in SKIP_FILES or p.suffix in SKIP_SUFFIX:
            continue
        yield rel.as_posix(), p


def encrypt(public_key_b64, value):
    from nacl import encoding, public
    box = public.SealedBox(public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder()))
    return base64.b64encode(box.encrypt(value.encode())).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="legends-channel")
    ap.add_argument("--secret", action="append", default=[], help="NAME=value (repeatable)")
    ap.add_argument("--var", action="append", default=[], help="NAME=value (repeatable)")
    ap.add_argument("--run", action="store_true", help="start a dry-run of the daily workflow and wait for the result")
    ap.add_argument("--real-run", action="store_true", help="with --run: do a real run (uploads to YouTube) instead of a dry run")
    ap.add_argument("--wait-minutes", type=int, default=45)
    a = ap.parse_args()
    token = os.environ.get("GH_TOKEN") or sys.exit("Set GH_TOKEN")
    gh = GH(token)

    me = gh.call("GET", "/user")
    login = me.json()["login"]
    scopes = me.headers.get("X-OAuth-Scopes")
    print(f"› signed in as {login}" + (f" (token scopes: {scopes})" if scopes else ""))
    if scopes is not None and "repo" not in scopes:
        sys.exit("The token needs the 'repo' permission.")
    can_workflow = scopes is None or "workflow" in scopes
    if not can_workflow:
        print("! the token has no 'workflow' permission: the scheduler file will be skipped (add the permission and run again)")

    # 1) repo (always private)
    r = gh.call("GET", f"/repos/{login}/{a.repo}", ok=(200, 404))
    if r.status_code == 404:
        gh.call("POST", "/user/repos", json={"name": a.repo, "private": True, "auto_init": True,
                                             "description": "Daily folklore videos (automated)"})
        print(f"› created private repo {login}/{a.repo}")
        time.sleep(3)
        r = gh.call("GET", f"/repos/{login}/{a.repo}")
    elif not r.json().get("private"):
        sys.exit("That repo exists and is PUBLIC. Refusing to put secrets next to public code: use another name.")
    branch = r.json().get("default_branch", "main")

    # 2) upload the project
    n = 0
    for rel, path in files_to_upload():
        if rel.startswith(".github/") and not can_workflow:
            continue
        url = f"/repos/{login}/{a.repo}/contents/{quote(rel)}"
        cur = gh.call("GET", url, ok=(200, 404), params={"ref": branch})
        body = {"message": f"add {rel}", "content": base64.b64encode(path.read_bytes()).decode(), "branch": branch}
        if cur.status_code == 200:
            body["sha"] = cur.json()["sha"]
        gh.call("PUT", url, json=body)
        n += 1
    print(f"› uploaded {n} files")

    # 3) secrets + variables
    if a.secret:
        pk = gh.call("GET", f"/repos/{login}/{a.repo}/actions/secrets/public-key").json()
        for item in a.secret:
            name, _, value = item.partition("=")
            if not value:
                continue
            gh.call("PUT", f"/repos/{login}/{a.repo}/actions/secrets/{name}",
                    json={"encrypted_value": encrypt(pk["key"], value), "key_id": pk["key_id"]})
            print(f"› secret stored: {name}")
    for item in a.var:
        name, _, value = item.partition("=")
        r = gh.call("POST", f"/repos/{login}/{a.repo}/actions/variables", ok=(201, 409), json={"name": name, "value": value})
        if r.status_code == 409:
            gh.call("PATCH", f"/repos/{login}/{a.repo}/actions/variables/{name}", json={"name": name, "value": value})
        print(f"› variable set: {name}={value}")

    # 4) test run
    if a.run and not can_workflow:
        print("› skipping the test run (no workflow file yet)")
    elif a.run:
        before = gh.call("GET", f"/repos/{login}/{a.repo}/actions/workflows/daily.yml/runs", params={"per_page": 1}).json()
        last = before["workflow_runs"][0]["id"] if before.get("workflow_runs") else 0
        gh.call("POST", f"/repos/{login}/{a.repo}/actions/workflows/daily.yml/dispatches",
                json={"ref": branch, "inputs": {"dry_run": "false" if a.real_run else "true"}})
        print("› started a " + ("REAL" if a.real_run else "dry") + " run; waiting…", flush=True)
        run, deadline = None, time.time() + a.wait_minutes * 60
        while time.time() < deadline:
            time.sleep(15)
            runs = gh.call("GET", f"/repos/{login}/{a.repo}/actions/workflows/daily.yml/runs", params={"per_page": 1}).json().get("workflow_runs", [])
            if runs and runs[0]["id"] != last:
                run = runs[0]
                if run["status"] == "completed":
                    break
        if not run or run["status"] != "completed":
            print("⏳ still running — check the Actions tab later:", f"https://github.com/{login}/{a.repo}/actions")
            return
        print(f"› run finished: {run['conclusion']}   {run['html_url']}")
        if run["conclusion"] != "success":
            jobs = gh.call("GET", f"/repos/{login}/{a.repo}/actions/runs/{run['id']}/jobs").json()["jobs"]
            for j in jobs:
                for st in j.get("steps", []):
                    if st.get("conclusion") == "failure":
                        print("  failed step:", st["name"])
            try:
                z = gh.call("GET", f"/repos/{login}/{a.repo}/actions/runs/{run['id']}/logs", ok=(200,))
                zf = zipfile.ZipFile(io.BytesIO(z.content))
                for name in zf.namelist():
                    if name.endswith(".txt") and "/" in name:
                        text = zf.read(name).decode("utf-8", "replace").splitlines()
                        err = [l for l in text if "Error" in l or "error" in l or "Traceback" in l]
                        if err:
                            print(f"--- {name} (last lines) ---")
                            print("\n".join(text[-25:]))
                            break
            except SystemExit:
                pass
            sys.exit(1)
    print("✔ done:", f"https://github.com/{login}/{a.repo}")


if __name__ == "__main__":
    main()
