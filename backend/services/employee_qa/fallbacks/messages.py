# Fixed replies of the knowledge assistant for every case that must not depend on the LLM
PEOPLE_TEAM = "people@northwind.example.test"

NOT_FOUND = ("I don't know: the company documents I can see don't cover this. "
             "Would you like me to pass your question to the People Team?")
REFUSED_PERSONAL = ("I can't look up personal records, yours or a colleague's. You can see your own leave balance, "
                    "payslips and profile in the People Portal; for anything else, the People Team can help.")
SENSITIVE = ("I'm sorry you're dealing with this. It deserves a personal, confidential conversation rather than an "
             f"automated answer. You can reach the People Team privately at {PEOPLE_TEAM} with \"Confidential\" in "
             "the subject. If anyone is in immediate danger, contact the emergency services. Would you like me to "
             "ask the People Team to contact you?")
BLOCKED = "I can only answer questions about Northwind Labs policies. Please rephrase your question."
ERROR = ("I can't answer right now because the assistant is unavailable. "
         "Would you like me to pass your question to the People Team?")
EMPTY = "Please type a question about a Northwind Labs policy."
