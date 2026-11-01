# Downloads the local prompt-injection classifier (ONNX) into models/ (gitignored) and records its SHA-256 hashes
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from security.injection_model import CHECKSUMS, sha256_file  # noqa: E402

REPO = "protectai/deberta-v3-base-prompt-injection-v2"  # Apache-2.0, not gated
TARGET = ROOT / "models" / "prompt-injection-v2"
FILES = ["onnx/model.onnx", "onnx/tokenizer.json", "onnx/config.json", "onnx/special_tokens_map.json"]


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    for remote in FILES:
        path = TARGET / Path(remote).name
        if path.is_file() and path.stat().st_size > 0:
            print(f"have  {path.relative_to(ROOT)} ({path.stat().st_size / 1e6:.1f} MB)")
            continue
        url = f"https://huggingface.co/{REPO}/resolve/main/{remote}"
        print(f"fetch {url}", flush=True)
        tmp = path.with_suffix(path.suffix + ".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(path)
        print(f"saved {path.relative_to(ROOT)} ({path.stat().st_size / 1e6:.1f} MB)")
    # The loader refuses files that no longer match these hashes (security/injection_model.py).
    checksums = {Path(remote).name: sha256_file(TARGET / Path(remote).name) for remote in FILES}
    (TARGET / CHECKSUMS).write_text(json.dumps({"source": REPO, "files": checksums}, indent=2), encoding="utf-8")
    print(f"Recorded SHA-256 of {len(checksums)} files in {(TARGET / CHECKSUMS).relative_to(ROOT)}")
    print(f"Model ready in {TARGET.relative_to(ROOT)}. Set SECURITY_MODEL_MODE=block (or monitor) in .env to use it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
