# Runs the drafter through the LangGraph orchestrator: draft, human review, then local "send"

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from core.approval_queue.approval_queue import ApprovalError, ApprovalItem  # noqa: E402
from core.paths import runtime_dir  # noqa: E402
from orchestrator.checkpoints import CHECKPOINT_FILE  # noqa: E402
from orchestrator.graph import TRIAGE_TASK, Orchestrator, WorkflowView  # noqa: E402


def show_item(item: ApprovalItem) -> None:
    proposal = item.proposal
    print(f"Approval ID: {item.id}")
    print(f"Status:      {item.status}")
    print(f"To:          {proposal['to']}")
    print(f"Subject:     {proposal['subject']}")
    print(f"Intent:      {proposal['intent']}")
    print(f"Warnings:    {', '.join(proposal['warnings']) or 'none'}")
    for claim in proposal["claims"]:
        print(f"Source:      {claim['source_field']} -> {claim['text']}")
    print(f"\n{proposal['body']}\n")


def show_view(orchestrator: Orchestrator, label: str, view: WorkflowView) -> None:
    reason = f" ({view.reason_code})" if view.reason_code else ""
    print(f"--- {label}: {view.status}{reason}")
    if view.message:
        print(view.message)
    if view.waiting_for_human and view.approval_id:
        show_item(orchestrator.workflow.queue.get(view.approval_id))


def _pending_item(orchestrator: Orchestrator, item_id: str) -> tuple[ApprovalItem, str]:
    item = orchestrator.workflow.queue.get(item_id)
    if item.status != "pending":
        raise ApprovalError(f"status_{item.status}")
    return item, orchestrator.paused_thread_for_email(item.in_reply_to)


def cmd_draft(orchestrator: Orchestrator, args: argparse.Namespace) -> int:
    inbox = orchestrator.workflow.mailbox.inbound()
    email_ids = [email["email_id"] for email in inbox] if args.all else [args.email_id]
    for email_id in email_ids:
        show_view(orchestrator, email_id, orchestrator.start(email_id))
    return 0


def cmd_triage(orchestrator: Orchestrator, args: argparse.Namespace) -> int:
    inbox = orchestrator.workflow.mailbox.inbound()
    email_ids = [email["email_id"] for email in inbox] if args.all else [args.email_id]
    for email_id in email_ids:
        view = orchestrator.start(email_id, task=TRIAGE_TASK)
        labels = view.classification or {}
        summary = f"{labels.get('type')} | urgency: {labels.get('urgency')} | from: {labels.get('sender_kind')}"
        print(f"=== {email_id}: {summary}")
        show_view(orchestrator, email_id, view)
    return 0


def cmd_list(orchestrator: Orchestrator, args: argparse.Namespace) -> int:
    for item in orchestrator.workflow.queue.list(args.status):
        print(f"{item.id}  {item.status:<11} {item.in_reply_to:<7} {item.proposal['to']}  {item.proposal['subject']}")
    return 0


def cmd_show(orchestrator: Orchestrator, args: argparse.Namespace) -> int:
    show_item(orchestrator.workflow.queue.get(args.id))
    return 0


def cmd_approve(orchestrator: Orchestrator, args: argparse.Namespace) -> int:
    item, thread_id = _pending_item(orchestrator, args.id)
    show_item(item)
    if not args.yes and input(f"Send this exact text as {args.by}? Type 'send' to confirm: ").strip() != "send":
        print("Not approved.")
        return 1
    decision = {"action": "approve", "reviewer": args.by, "reviewed_hash": item.payload_hash}
    view = orchestrator.resume(thread_id, decision)
    print(f"Result: {view.status}" + (f" ({view.reason_code})" if view.reason_code else ""))
    return 0 if view.status == "sent" else 1


def cmd_reject(orchestrator: Orchestrator, args: argparse.Namespace) -> int:
    _, thread_id = _pending_item(orchestrator, args.id)
    print(f"Result: {orchestrator.resume(thread_id, {'action': 'reject', 'reviewer': args.by}).status}")
    return 0


def cmd_edit(orchestrator: Orchestrator, args: argparse.Namespace) -> int:
    item, thread_id = _pending_item(orchestrator, args.id)
    subject = args.subject or item.proposal["subject"]
    body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else item.proposal["body"]
    view = orchestrator.resume(thread_id, {"action": "edit", "reviewer": args.by, "subject": subject, "body": body})
    show_view(orchestrator, item.in_reply_to, view)
    return 0


def cmd_redraft(orchestrator: Orchestrator, args: argparse.Namespace) -> int:
    item, thread_id = _pending_item(orchestrator, args.id)
    decision = {"action": "redraft", "reviewer": args.by, "feedback": args.feedback}
    show_view(orchestrator, item.in_reply_to, orchestrator.resume(thread_id, decision))
    return 0


def cmd_audit(orchestrator: Orchestrator, args: argparse.Namespace) -> int:
    audit = orchestrator.workflow.audit
    for entry in audit.entries():
        print(entry["at"], entry["event"], json.dumps(entry["fields"]))
    print(f"Chain intact: {audit.verify()}")
    return 0


def cmd_outbox(orchestrator: Orchestrator, args: argparse.Namespace) -> int:
    for sent in orchestrator.workflow.mailbox.outbox():
        print(f"--- {sent['sent_at']} to {sent['to']}: {sent['subject']}\n{sent['body']}\n")
    return 0


def cmd_graph(orchestrator: Orchestrator, args: argparse.Namespace) -> int:
    print(orchestrator.diagram())
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    # Evaluation results and review sheets in the eval folder are kept.
    files = ["approvals.sqlite3", "audit.jsonl", "outbox.jsonl", CHECKPOINT_FILE]
    files += [f"{CHECKPOINT_FILE}-wal", f"{CHECKPOINT_FILE}-shm"]
    for name in files:
        (runtime_dir() / name).unlink(missing_ok=True)
    print(f"Cleared the queue, audit log, outbox, and paused workflows in {runtime_dir()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    draft = commands.add_parser("draft", help="draft replies and pause each one for human review")
    target = draft.add_mutually_exclusive_group(required=True)
    target.add_argument("email_id", nargs="?")
    target.add_argument("--all", action="store_true")
    draft.set_defaults(handler=cmd_draft)

    triage = commands.add_parser("triage", help="classify emails, then draft the routine ones for review")
    triage_target = triage.add_mutually_exclusive_group(required=True)
    triage_target.add_argument("email_id", nargs="?")
    triage_target.add_argument("--all", action="store_true")
    triage.set_defaults(handler=cmd_triage)

    listing = commands.add_parser("list", help="list the approval queue")
    listing.add_argument("--status")
    listing.set_defaults(handler=cmd_list)

    show = commands.add_parser("show", help="show one draft")
    show.add_argument("id")
    show.set_defaults(handler=cmd_show)

    approve = commands.add_parser("approve", help="approve a draft and send it to the local outbox")
    approve.add_argument("id")
    approve.add_argument("--by", required=True)
    approve.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    approve.set_defaults(handler=cmd_approve)

    reject = commands.add_parser("reject", help="reject a draft")
    reject.add_argument("id")
    reject.add_argument("--by", required=True)
    reject.set_defaults(handler=cmd_reject)

    edit = commands.add_parser("edit", help="replace a draft's subject or body")
    edit.add_argument("id")
    edit.add_argument("--by", required=True)
    edit.add_argument("--subject")
    edit.add_argument("--body-file")
    edit.set_defaults(handler=cmd_edit)

    redraft = commands.add_parser("redraft", help="redraft using recruiter feedback")
    redraft.add_argument("id")
    redraft.add_argument("--by", required=True)
    redraft.add_argument("--feedback", required=True)
    redraft.set_defaults(handler=cmd_redraft)

    commands.add_parser("audit", help="print the audit log").set_defaults(handler=cmd_audit)
    commands.add_parser("outbox", help="print sent emails").set_defaults(handler=cmd_outbox)
    commands.add_parser("graph", help="print the workflow as a Mermaid diagram").set_defaults(handler=cmd_graph)
    commands.add_parser("reset", help="clear the local queue, audit log, outbox, and paused workflows")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "reset":
        return cmd_reset(args)
    try:
        return args.handler(Orchestrator(), args)
    except ApprovalError as error:
        print(f"Refused: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
