#!/usr/bin/env python3
"""Stage ONE run for a run_evals.py-style file protocol; never launch it.

Use an already frozen skill directory, not a moving working tree. Omitting --skill
prepares a no-skill control. The oracle, fixture generator and rubric stay outside.
The prompt's {python} placeholder becomes --python, or the Python running this script.
All created files remain inside this script's directory (runs/ by default).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("hard_media", HERE / "hard_media.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def tree_hashes(root):
    return {f.relative_to(root).as_posix(): m.sha(f) for f in sorted(root.rglob("*"))
            if f.is_file() and "__pycache__" not in f.parts and ".git" not in f.parts}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixtures", type=Path, default=HERE / "fixtures")
    ap.add_argument("--task", type=int, choices=[101, 102, 103, 104], required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--skill", type=Path)
    ap.add_argument("--run-root", type=Path, default=HERE / "runs")
    ap.add_argument("--python", help="Interpreter path written into the prompt (default: the Python running this script)")
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", args.name):
        raise SystemExit("Name must be 1-80 simple letters, digits, hyphens or underscores")
    suite = m.read_json(HERE / "hard-evals.json")
    entry = next(e for e in suite["evals"] if e["id"] == args.task)
    run = m.local_output(args.run_root / args.name / ".path-check").parent
    if any(run.iterdir()):
        raise SystemExit("Refusing to reuse a nonempty run directory")
    # Copy only explicitly enumerated public inputs, preserving their relative paths.
    for rel in entry["files"]:
        if not rel.startswith("input/") or ".." in Path(rel).parts:
            raise SystemExit("Unsafe suite file path")
        source = args.fixtures / entry["fixture_dir"] / rel[len("input/"):]
        dst = m.local_output(run / rel)
        shutil.copy2(source, dst)
    source_skill = {}
    if args.skill:
        skill = args.skill.resolve()
        if not (skill / "SKILL.md").is_file():
            raise SystemExit("--skill must be a frozen skill directory containing SKILL.md")
        source_skill = tree_hashes(skill)
        destination = run / ".agents/skills/legible-film"
        shutil.copytree(skill, destination, ignore=shutil.ignore_patterns("__pycache__", ".git"))
        if tree_hashes(skill) != source_skill or tree_hashes(destination) != source_skill:
            raise SystemExit("Skill changed while copying; do not run this staged job")
        intro = "The Legible Film skill is installed at .agents/skills/legible-film/. Read its SKILL.md and use its relevant references and tools. Use no other installed skills."
    else:
        intro = "Use no installed skills for this control run."
    if "{python}" not in suite["environment"]:
        raise SystemExit("Suite environment text has no {python} placeholder")
    python = args.python or Path(sys.executable).as_posix()
    prompt = intro + "\n\n" + suite["environment"].replace("{python}", python) + "\n\nRequest: " + entry["prompt"] + "\n"
    logs = m.local_output(args.run_root / "_logs/.path-check").parent
    (logs / f"{args.name}.prompt.txt").write_text(prompt, encoding="utf-8", newline="\n")
    jobs_file = logs / "jobs.txt"
    jobs = jobs_file.read_text(encoding="utf-8").splitlines() if jobs_file.exists() else []
    if args.name in jobs:
        raise SystemExit("Job name already in queue")
    jobs_file.write_text("\n".join(jobs + [args.name]) + "\n", encoding="utf-8")
    (logs / "parallel.txt").write_text("1\n", encoding="utf-8")
    m.dump(logs / f"{args.name}.custody.json", {"task": args.task,
        "fixture_seed": m.read_json(args.fixtures / "oracle/truth.json")["parameters"]["seed"],
        "input_hashes": tree_hashes(run / "input"), "skill_hashes": source_skill,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "suite_sha256": m.sha(HERE / "hard-evals.json"), "status": "prepared; no runner launched"})
    print(json.dumps({"run": str(run), "files": len(entry["files"]), "skill_installed": bool(args.skill),
                      "status": "prepared only"}))


if __name__ == "__main__":
    main()
