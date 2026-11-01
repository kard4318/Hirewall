# Terminal chat with the Northwind Labs knowledge assistant (local Ollama model or the offline extractive fake)
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from core.llm.client import LLMConfigError, get_llm  # noqa: E402
from services.employee_qa.answerer import KnowledgeAssistant  # noqa: E402
from services.employee_qa.extractive import extractive_llm  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask policy questions; answers come only from company documents.")
    parser.add_argument("--audience", choices=["employee", "hr"], default="employee")
    parser.add_argument("--mode", choices=["auto", "full", "retrieval"], default="auto")
    parser.add_argument("--llm", choices=["ollama", "fake"], help="default: LLM_PROVIDER")
    args = parser.parse_args()
    if not sys.stdin.isatty():
        sys.stdin.reconfigure(encoding="utf-8")
    load_dotenv(ROOT / ".env")
    try:
        assistant = KnowledgeAssistant(get_llm(args.llm, fake=extractive_llm()))
    except LLMConfigError as exc:
        print(f"FAILED: {exc}")
        return 1

    print(f"Northwind Labs knowledge assistant · audience={args.audience} · mode={args.mode}. Empty line or /quit to exit.\n")
    while True:
        try:
            question = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question or question == "/quit":
            break
        answer = assistant.ask(question, audience=args.audience, mode=args.mode)
        print(f"assistant> {answer.answer}")
        for c in answer.citations:
            print(f"   [{c.section_id}] {c.title} (v{c.version})")
        print(f"   kind={answer.kind} mode={answer.mode}" + (" escalation offered" if answer.escalation_offered else ""))
        if answer.notice:
            print(f"   note: {answer.notice}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
