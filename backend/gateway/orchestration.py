# Builds the shared screener and orchestrator on first use, so the gateway starts without them configured
import threading

from fastapi import FastAPI

from core.integrations.email_provider import email_sender_from_env
from gateway.candidate_notifier import CandidateNotifier
from orchestrator.graph import Orchestrator
from orchestrator.record_approval import RecordWorkflow
from services.screener.node import SCREEN_TASK, screen_job_node
from services.screener.service import ScreeningService

_lock = threading.Lock()


def screening_service(app: FastAPI) -> ScreeningService:
    if app.state.screening is None:
        with _lock:
            if app.state.screening is None:
                app.state.screening = ScreeningService()
    return app.state.screening


def shared_orchestrator(app: FastAPI) -> Orchestrator:
    """One orchestrator for email and screener workflows, so one queue holds everything awaiting a person."""
    screening = screening_service(app)
    if app.state.email_orchestrator is None:
        with _lock:
            if app.state.email_orchestrator is None:
                notifier = CandidateNotifier(screening, app.state.scheduling, email_sender_from_env())
                app.state.email_orchestrator = Orchestrator(
                    services={SCREEN_TASK: screen_job_node(screening)},
                    record_workflow=RecordWorkflow(build_action=screening.build_proposed_action, notifier=notifier),
                )
    return app.state.email_orchestrator
