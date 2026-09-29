import filecmp
import os
import shutil
import tempfile

from . import db, exporter, importer, paths


def _state_files(root):
    candidates = ["sources.json", "seen_listings.json", os.path.join("tracker", "companies.json"),
                  "collectors.json", "observed.json"]
    out = [name for name in candidates if os.path.isfile(os.path.join(root, name))]
    base = paths.companies_dir(os.path.join(root, "tracker"))
    if os.path.isdir(base):
        for cid in sorted(os.listdir(base)):
            cdir = os.path.join(base, cid)
            if not os.path.isdir(cdir):
                continue
            for name in ("postings.json", "crosswalk.json", "events.jsonl"):
                if os.path.isfile(os.path.join(cdir, name)):
                    out.append(os.path.join("tracker", "companies", cid, name))
    return out


def roundtrip(root=None):
    root = root or paths.home()
    expected = _state_files(root)

    tmp = tempfile.mkdtemp(prefix="jw-verify-")
    try:
        con = db.connect(os.path.join(tmp, "verify.db"))
        db.init(con)
        counts = importer.import_all(con, root)

        out_root = os.path.join(tmp, "out")
        os.makedirs(out_root, exist_ok=True)
        exporter.export_all(con, out_root)
        con.close()

        mismatches = []
        for rel in expected:
            original = os.path.join(root, rel)
            produced = os.path.join(out_root, rel)
            if not os.path.isfile(produced):
                mismatches.append({"file": rel, "reason": "not exported"})
            elif not filecmp.cmp(original, produced, shallow=False):
                mismatches.append({
                    "file": rel,
                    "reason": "bytes differ",
                    "original_size": os.path.getsize(original),
                    "exported_size": os.path.getsize(produced),
                })

        produced_all = set()
        for dirpath, _dirs, files in os.walk(out_root):
            for name in files:
                produced_all.add(
                    os.path.relpath(os.path.join(dirpath, name), out_root)
                )
        for extra in sorted(produced_all - set(expected)):
            mismatches.append({"file": extra, "reason": "exported but not in the source tree"})

        return {
            "ok": not mismatches,
            "files_compared": len(expected),
            "counts": counts,
            "mismatches": mismatches,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
