import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from tests import fixture  # noqa: E402
from tests.harness import (check, clean_env, finish, jsonl, run_jw, scalar,  # noqa: E402
                           table, help_lines)

PACKAGE_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "site")


def copy_package(dest, marker=None):
    shutil.copytree(os.path.join(REPO, "jw"), os.path.join(dest, "jw"), ignore=PACKAGE_IGNORE)
    if marker:
        with open(os.path.join(dest, marker), "w", encoding="utf-8") as fh:
            fh.write("[]\n")
    return dest


class Sandbox:
    def __init__(self, tmp):
        self.tmp = tmp
        self.cwd = os.path.join(tmp, "elsewhere")
        os.makedirs(self.cwd)

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)

    def jw(self, home, *args, stdin=None, **env):
        return run_jw(*args, env=clean_env(JW_HOME=home, **env), stdin=stdin, cwd=self.cwd,
                      python_path=REPO)


def check_init(box):
    home = box.path("home")
    code, out, err = box.jw(home, "init")
    check("init creates a home with a current-schema store",
          code == 0 and scalar(out, "created") == "true" and scalar(out, "schema_version") == "4"
          and os.path.isfile(os.path.join(home, "jobwatcher.db")))
    check("and the config the site and tools read",
          all(os.path.isfile(os.path.join(home, *p)) for p in (
              ("watchlist.json",), ("tracker", "companies.json"), ("tracker", "index.json"),
              ("tracker", "all_postings.json"))))
    check("and says where the home came from", scalar(out, "resolved_from") == "JW_HOME")
    check("init prints nothing to stderr", err == "")

    with open(os.path.join(home, "watchlist.json"), "w", encoding="utf-8") as fh:
        json.dump(["Acme"], fh)
    code, out, _ = box.jw(home, "init")
    with open(os.path.join(home, "watchlist.json"), encoding="utf-8") as fh:
        kept = json.load(fh)
    check("init is idempotent and never overwrites what is there",
          code == 0 and scalar(out, "created") == "false" and kept == ["Acme"])

    starter = box.path("starter-home")
    code, out, _ = box.jw(starter, "init", "--starter", "--git")
    with open(os.path.join(starter, "tracker", "companies.json"), encoding="utf-8") as fh:
        companies = json.load(fh)
    with open(os.path.join(starter, "collectors.json"), encoding="utf-8") as fh:
        collectors = json.load(fh)
    check("--starter adds the starter companies and the two Simplify sources",
          len(companies) == 34 and [c["name"] for c in collectors] == [
              "simplify:Summer2027-Internships", "simplify:New-Grad-Positions"])
    check("--git turns the home into a repository that ignores the database",
          os.path.isdir(os.path.join(starter, ".git"))
          and "jobwatcher.db" in open(os.path.join(starter, ".gitignore"), encoding="utf-8").read())
    code, out, _ = box.jw(starter, "init", "--starter")
    check("--starter never touches a home that already has companies",
          "skipped" in (scalar(out, "starter") or ""))
    code, out, _ = box.jw(starter, "--format", "json", "init", "--home", box.path("elsewhere-home"))
    check("--home overrides JW_HOME for that run and says how to keep it",
          code == 0 and os.path.isfile(box.path("elsewhere-home", "jobwatcher.db"))
          and any("JW_HOME=" in h for h in json.loads(out)["help"]))
    return home, starter


def check_doctor(box, home, starter):
    code, out, _ = box.jw(starter, "doctor")
    rows = {r["check"]: r for r in table(out, "checks")}
    check("doctor passes a healthy home and lists every check",
          code == 0 and scalar(out, "healthy") == "true" and rows["store"]["status"] == "ok"
          and rows["sources"]["detail"] == "2 enabled of 2")
    check("and flags what is merely missing as a warning with the fix",
          rows["last_sync"]["status"] == "warn" and any("jw sync run" in h for h in help_lines(out)))

    code, out, _ = box.jw(box.path("no-such-home"), "doctor")
    check("doctor fails a home that does not exist, exit 1, and says how to fix it",
          code == 1 and scalar(out, "code") == "UNHEALTHY"
          and any("jw init" in h for h in help_lines(out)))

    old = box.path("old-home")
    box.jw(old, "init")
    con = sqlite3.connect(os.path.join(old, "jobwatcher.db"))
    con.executescript("DROP TABLE collectors; DROP TABLE observed; "
                      "UPDATE meta SET value='3' WHERE key='schema_version';")
    con.commit()
    con.close()
    code, out, _ = box.jw(old, "doctor")
    check("doctor warns about an outdated schema and names the fix",
          code == 0 and any("jw db migrate" in h for h in help_lines(out)))
    code, out, _ = box.jw(old, "postings", "query")
    check("other commands refuse an outdated store with SCHEMA_OUTDATED and exit 2",
          code == 2 and scalar(out, "code") == "SCHEMA_OUTDATED")
    code, out, _ = box.jw(old, "db", "migrate")
    check("db migrate upgrades it", code == 0 and scalar(out, "schema_version") == "4")
    code, out, _ = box.jw(old, "source", "list")
    check("and the new tables work afterwards", code == 0 and scalar(out, "count") == "0")


def check_migration_keeps_data(box):
    root = box.path("legacy-tree")
    fixture.build_tree(root)
    for name in ("collectors.json", "observed.json"):
        os.remove(os.path.join(root, name))
    home = box.path("migrating")
    code, out, _ = box.jw(home, "db", "import", "--root", root)
    con = sqlite3.connect(os.path.join(home, "jobwatcher.db"))
    con.executescript("DROP TABLE collectors; DROP TABLE observed; "
                      "UPDATE meta SET value='3' WHERE key='schema_version';")
    con.commit()
    con.close()
    box.jw(home, "db", "migrate")
    body = json.loads(box.jw(home, "--format", "json", "state", "show")[1])
    check("a v3 store keeps every posting and listing through the v4 migration",
          body["schema_version"] == 4 and body["counts"]["postings"] == 2
          and body["counts"]["listings"] == 2)


def check_resolution(box):
    checkout = copy_package(box.path("checkout"), marker="sources.json")
    env_base = clean_env()

    def doctor_home(env, at):
        code, out, _ = run_jw("doctor", env=env, cwd=box.cwd, python_path=at)
        row = [r for r in table(out, "checks") if r["check"] == "home"][0]
        return row["detail"]

    detail = doctor_home(env_base, checkout)
    check("a checkout with legacy state files is its own home", detail.endswith("(checkout)")
          and "checkout" in detail)
    detail = doctor_home(dict(env_base, JW_HOME=box.path("explicit")), checkout)
    check("JW_HOME wins over the checkout", detail.endswith("(JW_HOME)"))
    detail = doctor_home(dict(env_base, JOBWATCHER_ROOT=box.path("legacy-env")), checkout)
    check("JOBWATCHER_ROOT still works as an alias", detail.endswith("(JOBWATCHER_ROOT)"))

    bare = copy_package(box.path("bare"))
    fake = box.path("fakehome")
    os.makedirs(fake)
    env = dict(env_base, HOME=fake, USERPROFILE=fake, LOCALAPPDATA=os.path.join(fake, "Local"),
               XDG_DATA_HOME=os.path.join(fake, "share"))
    code, out, _ = run_jw("--format", "json", "init", env=env, cwd=box.cwd, python_path=bare)
    if sys.platform == "win32":
        expected = os.path.join(fake, "Local", "jobwatcher")
    elif sys.platform == "darwin":
        expected = os.path.join(fake, "Library", "Application Support", "jobwatcher")
    else:
        expected = os.path.join(fake, "share", "jobwatcher")
    check("with no env and no legacy files the home is the platform data directory",
          code == 0 and json.loads(out)["resolved_from"] == "default"
          and os.path.isfile(os.path.join(expected, "jobwatcher.db")))


def check_data_stays_in_home(box):
    home = box.path("contained")
    elsewhere = os.listdir(box.cwd)
    observation = {"source": "adhoc", "external_id": "adhoc:1", "company_raw": "Acme Corp",
                   "title_raw": "Engineer"}
    box.jw(home, "init")
    code, out, _ = box.jw(home, "ingest", "--track-all", stdin=jsonl([observation]))
    check("ingest works in a fresh home", code == 0 and scalar(out, "observations") == "1")
    check("and every file it wrote is under the home, none in the working directory",
          os.listdir(box.cwd) == elsewhere
          and os.path.isfile(os.path.join(home, "tracker", "companies", "acme", "postings.json")))


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def get(url):
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status, resp.read()


def check_package(box):
    project = box.path("project")
    os.makedirs(os.path.join(project, "docs"))
    for name in ("pyproject.toml", "setup.py", "MANIFEST.in", "LICENSE", "README.md"):
        shutil.copy2(os.path.join(REPO, name), project)
    copy_package(project)
    shutil.copy2(os.path.join(REPO, "docs", "index.html"), os.path.join(project, "docs"))
    shutil.copytree(os.path.join(REPO, "docs", "assets"), os.path.join(project, "docs", "assets"))

    dist = box.path("dist")
    proc = subprocess.run([sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-q",
                           "-w", dist], cwd=project, capture_output=True, text=True)
    wheels = [f for f in os.listdir(dist)] if os.path.isdir(dist) else []
    check("the project builds a wheel (this check needs network to fetch setuptools)",
          proc.returncode == 0 and len(wheels) == 1)
    if not wheels:
        print(proc.stderr[-800:])
        return
    wheel = os.path.join(dist, wheels[0])
    names = zipfile.ZipFile(wheel).namelist()
    check("the wheel bundles the built site and the starter data",
          "jw/site/index.html" in names and any(n.startswith("jw/site/assets/") for n in names)
          and "jw/starter/companies.json" in names)
    check("and every runtime module, including the built-in collector and the contract",
          all(f"jw/{m}" in names for m in ("cli.py", "reconcile.py", "normalize.py", "schema.py",
                                          "ingest.py", "collectors/simplify.py", "skills.py",
                                          "agent_hooks.py")))
    check("and the guide topics agents install as skills",
          all(f"jw/guide/{m}" in names for m in ("__init__.py", *(f"{t}.md" for t in
              ("setup", "core", "track-applications", "write-collector", "notify", "triage")))))
    check("and nothing from routine/ or the web sources",
          not any(n.startswith(("routine/", "web/")) for n in names))
    check("and none of jw's own test suites",
          not any(n.startswith("jw/test_") for n in names))

    setuptools_dir = box.path("build-setuptools")
    proc = subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "-q",
                           "--target", setuptools_dir, "setuptools"],
                          capture_output=True, text=True)
    check("a throwaway setuptools installs for building the sdist", proc.returncode == 0)
    sdist_dir = box.path("sdist")
    proc = subprocess.run([sys.executable, "setup.py", "sdist", "-d", sdist_dir], cwd=project,
                          capture_output=True, text=True,
                          env=dict(os.environ, PYTHONPATH=setuptools_dir))
    sdists = [f for f in os.listdir(sdist_dir)] if os.path.isdir(sdist_dir) else []
    check("the project also builds an sdist", proc.returncode == 0 and len(sdists) == 1)
    if sdists:
        with tarfile.open(os.path.join(sdist_dir, sdists[0])) as tar:
            sdist_names = tar.getnames()
        check("the sdist keeps jw's test suites, unlike the wheel",
              all(any(n.endswith(f"jw/{m}") for n in sdist_names)
                  for m in ("test_cli.py", "test_home.py", "test_ingest.py", "test_jw.py")))

    target = box.path("installed")
    proc = subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "-q",
                           "--target", target, wheel], capture_output=True, text=True)
    check("the wheel installs", proc.returncode == 0)

    home = box.path("pkg-home")
    env = clean_env(JW_HOME=home)
    run = lambda *a: run_jw(*a, env=env, cwd=box.cwd, python_path=target)  # noqa: E731
    code, out, _ = run("init", "--starter")
    check("the installed package initialises a home with no checkout around",
          code == 0 and scalar(out, "created") == "true")
    code, out, _ = run("doctor")
    site_row = [r for r in table(out, "checks") if r["check"] == "site"][0]
    check("and finds its bundled site", "jw/site" in site_row["detail"].replace("\\", "/"))

    code, out, _ = run("guide", "write-collector")
    check("the installed package's guide reads a real topic",
          code == 0 and scalar(out, "topic") == "write-collector" and "jw schema observation" in out)
    agent_project = box.path("agent-project")
    code, out, _ = run("skills", "install", "--root", agent_project)
    check("and installs skills from the wheel's bundled guide, not a checkout",
          code == 0 and os.path.isfile(
              os.path.join(agent_project, ".agents", "skills", "jw-core", "SKILL.md")))
    code, out, _ = run("hooks", "install", "--root", agent_project)
    check("and registers the session-start hook",
          code == 0 and scalar(out, "action") == "installed" and os.path.isfile(
              os.path.join(agent_project, ".claude", "settings.json")))

    port = free_port()
    server = subprocess.Popen([sys.executable, "-m", "jw", "serve", "--port", str(port)],
                              cwd=box.cwd, env=dict(env, PYTHONPATH=target),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                get(base + "/api/health")
                break
            except OSError:
                time.sleep(0.2)
        status, body = get(base + "/")
        check("jw serve from the installed package serves the bundled site",
              status == 200 and b"<html" in body.lower())
        status, body = get(base + "/tracker/index.json")
        check("and the data from the home", status == 200 and len(json.loads(body)["companies"]) == 34)
        status, body = get(base + "/api/health")
        check("and the API", status == 200 and json.loads(body)["service"] == "jw-serve")
    finally:
        server.kill()
        server.wait()


def main():
    tmp = tempfile.mkdtemp(prefix="jw-home-")
    try:
        box = Sandbox(tmp)
        home, starter = check_init(box)
        check_doctor(box, home, starter)
        check_migration_keeps_data(box)
        check_resolution(box)
        check_data_stays_in_home(box)
        check_package(box)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return finish()


if __name__ == "__main__":
    sys.exit(main())
