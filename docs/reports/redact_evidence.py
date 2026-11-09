"""Redact account/contact names from the preserved evidence, keeping every number.

The evidence files mix measurements (which must stay byte-identical) with UI
labels that came from the signed-in account (which must not be published).
Only the label strings change; replacement is a fixed map so a re-run is stable.
"""

import json
import pathlib
import sys

REDACT = {
    "残刃的头像": "<account-avatar>",
    "残刃": "<account>",
    "我的手机": "<device>",
    "源码技术沟通交流": "<group-a>",
    "Alsai交流反馈群": "<group-b>",
}


def scrub(value):
    if isinstance(value, str):
        return REDACT.get(value, value)
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items()}
    return value


def main() -> int:
    root = pathlib.Path(sys.argv[1])
    for path in sorted(root.glob("*.json")):
        original = json.loads(path.read_text(encoding="utf-8"))
        cleaned = scrub(original)
        text = json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n"
        path.write_text(text, encoding="utf-8")
        changed = original != cleaned
        print(f"{path.name}: {'redacted' if changed else 'unchanged'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
