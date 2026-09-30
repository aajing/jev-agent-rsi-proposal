"""Deterministic public source package. Private Judge assets are never included."""
import hashlib
import json
from pathlib import Path
import zipfile

BASE = Path(__file__).resolve().parent
FILES = ["README.md", "SUBMISSION.md", "proposal.md", "TASK_SPEC.md", "GAME_TASKS.md", "RUNBOOK.md",
         "IMPLEMENTATION_STATUS.md", "baseline_prompts.json", "package_submission.py", ".gitignore"]
DIRS = ["jevbench", "configs", "assets", "tests", "scripts", "harbor", "data/public"]
EXCLUDE = {"private", "__pycache__", ".pytest_cache", ".cache", "context", "trusted", "prepared"}


def main():
    chosen = [BASE/f for f in FILES if (BASE/f).is_file()]
    for directory in DIRS:
        for path in (BASE/directory).rglob("*"):
            relative = path.relative_to(BASE)
            if path.is_file() and not path.is_symlink() and not EXCLUDE.intersection(relative.parts) and path.suffix not in {".pyc", ".so", ".dylib"} and path.name != ".fifteen_solver":
                chosen.append(path)
    for name in ("data/manifest.json", "evidence/readiness.json", "evidence/cpu_checks.json", "evidence/tokenizer_checks.json", "evidence/official_static_checks.json"):
        if (BASE/name).is_file():
            chosen.append(BASE/name)
    payload = {str(p.relative_to(BASE)):p.read_bytes() for p in sorted(set(chosen))}
    assert not any("private" in Path(name).parts for name in payload)
    manifest = {"schema_version":1,"status":"implemented_cpu_validated_gpu_pending",
        "files":{name:{"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()} for name,data in payload.items()},
        "private_judge_assets_included":False,"model_weights_included":False}
    payload["PUBLIC_PACKAGE_MANIFEST.json"] = (json.dumps(manifest, indent=2, sort_keys=True)+"\n").encode()
    dest = BASE / "dist/jev-agent-proposal.zip"
    dest.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(payload.items()):
            info = zipfile.ZipInfo(name, (2026,9,30,0,0,0))
            info.create_system = 3
            info.external_attr = (0o100755 if name.endswith(".sh") else 0o100644) << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    with zipfile.ZipFile(dest) as archive:
        assert archive.testzip() is None
        assert all(archive.read(name) == data for name,data in payload.items())
    sha = hashlib.sha256(dest.read_bytes()).hexdigest()
    dest.with_suffix(".sha256").write_text(f"{sha}  {dest.name}\n")
    print(json.dumps({"archive":str(dest),"files":len(payload),"bytes":dest.stat().st_size,"sha256":sha}))


if __name__ == "__main__":
    main()
