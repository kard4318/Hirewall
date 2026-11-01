# Fixed reply and email templates; used directly or whenever the LLM output fails validation
from services.scheduler.conversation.formatting import SLOT, SLOTS

LINK_INVALID = "This booking link is invalid or has expired. Please contact HR for a new link."
MESSAGE_BLOCKED = ("Sorry, I can't process that message. Please write a short message about when you are "
                   "available for your interview, or contact HR.")
TOKEN_REASONS = {"invalid_token", "unknown_candidate", "not_approved"}
RATE_LIMITED = "You're sending messages very quickly. Please wait a minute and try again."
TURN_LIMIT = "This conversation has reached its limit. Please contact HR and they will help you finish scheduling."

FIXED = {
    "error": "Sorry, something went wrong on our side and nothing was booked. Please try again in a moment, or contact HR.",
    "already_booked": f"You already have an interview booked: {SLOT}. To change it, please reply to your confirmation email and HR will help.",
    "unknown_slot": f"I couldn't match that to one of the options I offered. Please pick one of these: {SLOTS}",
    "unknown_slot_none": "I haven't offered you any times yet. Tell me when suits you and I'll suggest some.",
    "booking_rejected": "This time could not be approved, so nothing was booked. Would you like to choose another time?",
    "search_limit": ("I've shared all the options I can here. Please pick one of the times above, "
                     "or contact HR and they will help you find another time."),
}

FALLBACKS = {
    "slots_offered": f"Here are the times I can offer: {SLOTS}Which one works best for you? You can reply with its number.",
    "slots_offered_more": f"Sure, here are some other free times: {SLOTS}Does one of these work better? You can reply with its number.",
    "confirm_slot": f"You picked {SLOT}. Shall I book it? Reply yes to confirm, or no to choose another time.",
    "need_choice": f"Please pick one of the offered times first: {SLOTS}",
    "need_choice_none": "Tell me when suits you and I'll suggest some interview times.",
    "declined": "No problem. Tell me what suits you better and I'll look for other times.",
    "booked": f"Your interview is booked for {SLOT}. A confirmation email is on its way.",
    "slot_taken": f"Sorry, that time was just taken. Here are the current options: {SLOTS}",
    "slot_taken_none": "Sorry, that time was just taken, and I have no other free times right now. HR will contact you.",
    "answer": "Thanks for your question. I'll pass it on to HR, who will get back to you.",
    "no_slots_fully_booked": "Sorry, that day is fully booked. Would another day work for you?",
    "no_slots_weekend": "Interviews only take place on working days. Would a weekday work for you?",
    "no_slots_outside_window": "I can only offer times in the coming days. Could you suggest something sooner?",
    "no_slots_no_match": "I couldn't find a free time matching that. Could you widen your preference a little?",
    "no_slots_no_more": "Those were all the free times I have in the coming days. Would one of them work, or shall I ask HR to contact you?",
}

SITUATIONS = {
    "slots_offered": "You are offering the candidate a numbered list of interview times and asking which one suits them.",
    "slots_offered_more": ("The candidate asked for other options. You are offering new interview times, different from "
                           "the ones shown before, and asking which one suits them."),
    "slots_offered_preference": ("The candidate described when they are available. You are offering interview times "
                                 "that match their preference and asking which one suits them."),
    "confirm_slot": "The candidate picked a time. Ask them to confirm it with yes, or say no to pick another.",
    "need_choice": "The candidate tried to confirm, but has not picked a time yet. Ask them to pick one from the list.",
    "declined": "The candidate does not want the proposed time. Ask what suits them better.",
    "booked": "The interview is booked for the chosen time and a confirmation email was sent.",
    "slot_taken": "The time the candidate chose was just taken by someone else. Apologise and show the new options.",
    "no_slots": "No free interview time matches the candidate's request. Ask them to suggest another preference.",
    "no_slots_no_more": ("The candidate asked for more options, but every free time in the coming days was already "
                         "shown. Suggest picking one of those, or offer that HR contacts them."),
}


def fallback_for(kind: str, reason: str | None = None, has_slots: bool = True) -> str:
    if kind == "no_slots":
        return FALLBACKS.get(f"no_slots_{reason}", FALLBACKS["no_slots_no_match"])
    if kind in ("need_choice", "slot_taken") and not has_slots:
        return FALLBACKS[f"{kind}_none"]
    base = kind.rsplit("_", 1)[0]  # e.g. slots_offered_preference -> slots_offered
    return FALLBACKS.get(kind) or FIXED.get(kind) or FALLBACKS.get(base) or FIXED["error"]


CANDIDATE_EMAIL_SUBJECT = "Your interview for {job_title} is confirmed"
CANDIDATE_EMAIL_BODY = (
    "Hi {first_name},\n\n"
    "Your interview for the {job_title} position is booked for {slot} ({timezone}).\n"
    "Calendar link: {link}\n\n"
    "If you need to reschedule, reply to this email and our HR team will help.\n\n"
    "The HR team"
)
HR_EMAIL_SUBJECT = "Interview booked: {candidate_name} - {job_title}"
HR_EMAIL_BODY = (
    "An interview was booked through the scheduling assistant.\n\n"
    "Candidate: {candidate_name}\n"
    "Position: {job_title}\n"
    "Time: {slot} ({timezone})\n"
    "Calendar link: {link}\n"
)
