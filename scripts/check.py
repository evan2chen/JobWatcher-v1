import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO, "web")

SUITES = [
    ("routine engine", [sys.executable, "routine/test_run.py"], REPO),
    ("jw store and CLI", [sys.executable, "jw/test_jw.py"], REPO),
    ("jw CLI output (end to end)", [sys.executable, "jw/test_cli.py"], REPO),
    ("jw home, init, doctor and packaging (needs network for the wheel build)",
     [sys.executable, "jw/test_home.py"], REPO),
    ("jw ingest, collectors and legacy parity", [sys.executable, "jw/test_ingest.py"], REPO),
    ("web typecheck", ["npm", "run", "typecheck"], WEB),
    ("web logic smoke (live corpus)", ["npm", "run", "smoke"], WEB),
]

BROWSER_SUITE = ("web E2E (Playwright)", ["npm", "run", "e2e"], WEB)


def run_suite(name, command, cwd):
    print(f"\n=== {name} ===")
    proc = subprocess.run(command, cwd=cwd, shell=(sys.platform == "win32" and command[0] == "npm"))
    if proc.returncode != 0:
        print(f"FAILED: {name} (exit {proc.returncode})")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="The full JobWatcher test gate")
    parser.add_argument("--no-browser", action="store_true",
                        help="skip the Playwright suite when web/ is untouched")
    args = parser.parse_args()

    suites = list(SUITES)
    if not args.no_browser:
        suites.append(BROWSER_SUITE)

    for name, command, cwd in suites:
        if not run_suite(name, command, cwd):
            print(f"\nGATE FAILED: {name}")
            return 1

    print("\nGATE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
