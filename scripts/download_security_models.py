# Downloads the local prompt-injection classifier (ONNX) into models/ (gitignored); run once, then works offline
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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
    print(f"Model ready in {TARGET.relative_to(ROOT)}. Set SECURITY_MODEL_MODE=block (or monitor) in .env to use it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
