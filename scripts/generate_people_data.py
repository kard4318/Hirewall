# Generates the synthetic Northwind Labs workforce (data/people/) and 8 weeks of synthetic agent audit events
import argparse
import csv
import json
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PEOPLE_DIR = ROOT / "data" / "people"
AUDIT_FILE = ROOT / "data" / "runtime" / "audit_events.jsonl"
DEFAULT_AS_OF = date(2026, 11, 1)
START = date(2021, 1, 1)
TZ = timezone(timedelta(hours=1))

AGE_BANDS = ["<25", "25-34", "35-44", "45-54", "55+"]
SITES = ["Tunis", "Paris", "Remote"]
# active, leavers (besides the planted Support exits), age weights, site weights, hire-year weights (2021..2026)
DEPARTMENTS = {
    "Engineering":      dict(active=120, leavers=8,  ages=[6, 44, 34, 12, 4],  sites=[50, 25, 25], years=[32, 24, 16, 12, 9, 7]),
    "Support":          dict(active=80,  leavers=25, ages=[30, 46, 15, 6, 3],  sites=[70, 10, 20], years=[6, 10, 14, 20, 26, 24]),
    "Sales":            dict(active=60,  leavers=28, ages=[14, 46, 24, 11, 5], sites=[40, 50, 10], years=[8, 12, 16, 20, 24, 20]),
    "Product & Design": dict(active=50,  leavers=14, ages=[10, 50, 28, 9, 3],  sites=[35, 35, 30], years=[10, 14, 18, 20, 22, 16]),
    "Operations":       dict(active=50,  leavers=13, ages=[5, 22, 32, 26, 15], sites=[75, 15, 10], years=[20, 20, 19, 16, 14, 11]),
    "People & Finance": dict(active=40,  leavers=12, ages=[8, 38, 32, 15, 7],  sites=[55, 35, 10], years=[12, 14, 18, 20, 20, 16]),
}
TITLES = {
    "Engineering": ["Junior Engineer", "Engineer", "Senior Engineer", "Staff Engineer", "Engineering Manager"],
    "Support": ["Support Associate", "Support Specialist", "Senior Support Specialist", "Support Lead", "Head of Support"],
    "Sales": ["Sales Associate", "Account Executive", "Senior Account Executive", "Sales Lead", "Head of Sales"],
    "Product & Design": ["Junior Designer", "Product Designer", "Senior Product Designer", "Product Manager", "Head of Product"],
    "Operations": ["Operations Assistant", "Operations Coordinator", "Operations Analyst", "Operations Lead", "Head of Operations"],
    "People & Finance": ["HR Assistant", "People Partner", "Finance Analyst", "Senior People Partner", "Head of People & Finance"],
}
VOLUNTARY_REASONS = ["career_growth", "compensation", "management", "relocation", "personal"]
COURSES = ["Security awareness", "Data protection basics", "Inclusive hiring", "Feedback skills", "Product discovery",
           "Advanced SQL", "Customer empathy", "Negotiation", "Time management", "Python for analysts"]
FIELDS = ["employee_id", "department", "job_title", "level", "site", "contract", "hire_date", "end_date", "exit_type",
          "exit_reason", "age_band", "gender", "manager_id"]


def pick(rng: random.Random, options: list, weights: list):
    return rng.choices(options, weights=weights, k=1)[0]


def random_date(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, max((end - start).days, 0)))


def hire_date_for(rng: random.Random, years: list[int], latest: date) -> date:
    year = pick(rng, [2021, 2022, 2023, 2024, 2025, 2026], years)
    start = date(year, 1, 1)
    end = min(date(year, 12, 31), latest)
    return random_date(rng, start, end) if start <= end else random_date(rng, START, latest)


def level_for(rng: random.Random, age_band: str, contract: str) -> str:
    if contract == "intern":
        return "L1"
    base = {"<25": [70, 25, 5, 0, 0], "25-34": [20, 45, 28, 6, 1], "35-44": [4, 22, 42, 24, 8],
            "45-54": [2, 12, 36, 32, 18], "55+": [1, 10, 30, 34, 25]}[age_band]
    return pick(rng, ["L1", "L2", "L3", "L4", "L5"], base)


def person(rng: random.Random, dept: str, spec: dict, contract_weights: list[int], hire: date) -> dict:
    contract = pick(rng, ["permanent", "fixed_term", "intern"], contract_weights)
    age = "<25" if contract == "intern" else pick(rng, AGE_BANDS, spec["ages"])
    level = level_for(rng, age, contract)
    return {
        "department": dept, "level": level, "job_title": TITLES[dept][int(level[1]) - 1],
        "site": pick(rng, SITES, spec["sites"]), "contract": contract, "hire_date": hire, "end_date": None,
        "exit_type": "", "exit_reason": "", "age_band": age, "gender": pick(rng, ["F", "M", "undisclosed"], [46, 48, 6]),
    }


def make_leaver(rng: random.Random, dept: str, spec: dict, end: date, exit_type: str, reason: str) -> dict:
    tenure_days = rng.randint(70, 1500)
    hire = end - timedelta(days=tenure_days)
    if hire < START:  # keep early leavers spread out instead of all starting on 1 January 2021
        hire = random_date(rng, START, end - timedelta(days=60))
    p = person(rng, dept, spec, [44, 26, 30], hire)  # (4) interns and fixed-term leave far more often
    if exit_type == "retirement":
        p["age_band"], p["contract"] = "55+", "permanent"
    p.update(end_date=end, exit_type=exit_type, exit_reason=reason)
    return p


def random_exit(rng: random.Random) -> tuple[str, str]:
    kind = pick(rng, ["voluntary", "involuntary", "retirement"], [74, 20, 6])
    if kind == "voluntary":
        return kind, pick(rng, VOLUNTARY_REASONS, [30, 26, 18, 14, 12])
    if kind == "involuntary":
        return kind, pick(rng, ["performance", "restructuring"], [60, 40])
    return kind, "retirement"


def generate_employees(rng: random.Random, as_of: date) -> list[dict]:
    people: list[dict] = []
    last_hire = as_of - timedelta(days=1)
    for dept, spec in DEPARTMENTS.items():
        for _ in range(spec["active"]):
            people.append(person(rng, dept, spec, [86, 9, 5], hire_date_for(rng, spec["years"], last_hire)))
        for _ in range(spec["leavers"]):
            # Ordinary exits, spread over the years and avoiding the planted Support quarters.
            end = random_date(rng, date(2021, 7, 1), as_of - timedelta(days=2))
            people.append(make_leaver(rng, dept, spec, end, *random_exit(rng)))
    support = DEPARTMENTS["Support"]
    # (1) Support spike: 13 exits in 2026Q2 (10 career_growth), still elevated with 6 exits in 2026Q3.
    for reason in ["career_growth"] * 10 + ["compensation", "compensation", "management"]:
        people.append(make_leaver(rng, "Support", support, random_date(rng, date(2026, 4, 1), date(2026, 6, 30)),
                                  "voluntary", reason))
    for reason in ["career_growth"] * 3 + ["compensation", "personal", "management"]:
        people.append(make_leaver(rng, "Support", support, random_date(rng, date(2026, 7, 1), date(2026, 9, 30)),
                                  "voluntary", reason))
    # Stable ids in hiring order; managers are senior people (L4/L5) of the same department, hired earlier.
    people.sort(key=lambda p: (p["hire_date"], p["department"], p["level"]))
    for i, p in enumerate(people, start=1):
        p["employee_id"] = f"E-{i:04d}"
    for p in people:
        seniors = [m for m in people if m["department"] == p["department"] and m["level"] in ("L4", "L5")
                   and m["hire_date"] <= p["hire_date"] and m is not p]
        p["manager_id"] = rng.choice(seniors)["employee_id"] if seniors and p["level"] != "L5" else ""
    return people


def quarters(first: tuple[int, int], last: tuple[int, int]) -> list[tuple[int, int]]:
    result, (y, q) = [], first
    while (y, q) <= last:
        result.append((y, q))
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return result


def quarter_end(y: int, q: int) -> date:
    return date(y, 3 * q, 31 if q in (1, 4) else 30)


def active_on(p: dict, day: date) -> bool:
    return p["hire_date"] <= day and (p["end_date"] is None or p["end_date"] > day)


def generate_engagement(rng: random.Random, people: list[dict]) -> list[dict]:
    base = {"Engineering": 3.9, "Support": 3.75, "Sales": 3.5, "Product & Design": 3.9, "Operations": 3.6,
            "People & Finance": 3.8}
    site_offset = {"Tunis": 0.0, "Paris": -0.12, "Remote": 0.15}  # (5) Remote a little above Paris
    support_dip = {(2026, 1): -0.6, (2026, 2): -0.8, (2026, 3): -0.45}  # (1) engagement dip around the spike
    rows = []
    for y, q in quarters((2022, 1), (2026, 3)):
        end = quarter_end(y, q)
        for dept in DEPARTMENTS:
            for site in SITES:
                headcount = sum(1 for p in people if p["department"] == dept and p["site"] == site and active_on(p, end))
                if headcount == 0:
                    continue
                rate = round(rng.uniform(0.62, 0.86), 2)
                score = base[dept] + site_offset[site] + rng.uniform(-0.08, 0.08)
                if dept == "Support":
                    score += support_dip.get((y, q), 0.0)
                rows.append({"quarter": f"{y}Q{q}", "department": dept, "site": site,
                             "score": f"{min(5.0, max(1.0, score)):.1f}", "response_rate": f"{rate:.2f}",
                             "respondents": max(0, round(headcount * rate))})
    return rows


def generate_training(rng: random.Random, people: list[dict], as_of: date) -> list[dict]:
    rows = []
    for p in people:
        if not active_on(p, as_of):
            continue
        completion = 0.4 if p["department"] == "Sales" else 0.87  # (3) Sales lags behind
        for course in rng.sample(COURSES, k=rng.randint(1, 3)):
            rows.append({"employee_id": p["employee_id"], "course": course, "hours": rng.choice([2, 3, 4, 6, 8, 12, 16]),
                         "completed": "true" if rng.random() < completion else "false"})
    return rows


def generate_positions() -> list[dict]:
    return [
        {"job_id": "job-be", "department": "Engineering", "title": "Backend Developer", "opened_date": "2026-09-15", "status": "open"},
        {"job_id": "job-da", "department": "Operations", "title": "Data Analyst", "opened_date": "2026-09-22", "status": "open"},
        {"job_id": "job-pd", "department": "Product & Design", "title": "Product Designer", "opened_date": "2026-10-01", "status": "open"},
        {"job_id": "job-se", "department": "Sales", "title": "Account Executive", "opened_date": "2026-08-18", "status": "open"},
        {"job_id": "job-su", "department": "Support", "title": "Support Specialist", "opened_date": "2026-07-06", "status": "open"},
        {"job_id": "job-pp", "department": "People & Finance", "title": "People Partner", "opened_date": "2026-06-02", "status": "on_hold"},
    ]


def generate_audit_events(rng: random.Random, as_of: date) -> list[dict]:
    """8 Monday-to-Sunday weeks ending on or before as_of, with a slow upward trend. Every event is synthetic."""
    last_monday = as_of - timedelta(days=(as_of.weekday() + 1) % 7 + 6) if as_of.weekday() != 6 else as_of - timedelta(days=6)
    weeks = [last_monday - timedelta(weeks=7 - w) for w in range(8)]
    jobs = ["job-be", "job-da", "job-pd"]
    events: list[dict] = []

    def ts(monday: date) -> str:
        day = monday + timedelta(days=rng.randint(0, 4))
        moment = datetime(day.year, day.month, day.day, rng.randint(8, 17), rng.randint(0, 59), tzinfo=TZ)
        return moment.isoformat()

    def add(monday: date, event: str, actor: str, reason: str, **extra: str) -> None:
        events.append({"ts": ts(monday), "event": event, "actor": actor, "reason_code": reason,
                       "candidate_ref": f"C-{rng.randint(1000, 9999)}", "synthetic": True, **extra})

    for w, monday in enumerate(weeks):
        trend = 1 + 0.06 * w
        screened = round(36 * trend + rng.randint(-3, 3))
        shortlisted = round(screened * rng.uniform(0.2, 0.26))
        invited = round(shortlisted * rng.uniform(0.75, 0.9))
        booked = round(invited * rng.uniform(0.65, 0.8))
        for _ in range(screened):
            add(monday, "resume_screened", "agent", "screened", job_id=rng.choice(jobs))
        for _ in range(shortlisted):
            add(monday, "candidate_shortlisted", "agent", "score_above_threshold", job_id=rng.choice(jobs))
        for _ in range(invited):
            add(monday, "invitation_created", "human", "hr_invited", job_id=rng.choice(jobs))
        for _ in range(booked):
            add(monday, "booking_created", "agent", "candidate_confirmed", job_id=rng.choice(jobs))
        for _ in range(rng.randint(0, 2)):
            add(monday, "booking_cancelled", "human", "hr_cancelled", job_id=rng.choice(jobs))
        for _ in range(rng.randint(4, 9)):
            add(monday, "reminder_drafted", "agent", "no_reply_48h", job_id=rng.choice(jobs))
        for _ in range(round(16 * trend + rng.randint(-2, 3))):
            add(monday, "approval_decided", "human", "queue_review",
                outcome=pick(rng, ["approve", "edit", "reject"], [75, 15, 10]))
        for _ in range(round(22 * trend + rng.randint(-3, 3))):
            add(monday, "kb_question", "agent", "kb", outcome=pick(rng, ["answered", "escalated"], [80, 20]),
                topic=rng.choice(["leave", "remote work", "expenses", "benefits", "it equipment", "onboarding"]))
        for _ in range(rng.randint(2, 5)):
            add(monday, "message_blocked", "agent",
                pick(rng, ["injection_suspected", "rate_limited", "message_too_long", "invalid_token"], [50, 20, 15, 15]))
    for e in events:  # the pseudonymous candidate reference is irrelevant for KB and blocked-message events
        if e["event"] in ("kb_question", "message_blocked", "approval_decided"):
            e.pop("candidate_ref")
    return sorted(events, key=lambda e: e["ts"])


# Fictional names for the HR directory. Drawn from their own random stream so the analytics data never changes.
FIRST_F = ["Amira", "Ines", "Salma", "Yasmine", "Nour", "Rania", "Leila", "Mariem", "Sarra", "Hela", "Emma", "Lea",
           "Chloe", "Camille", "Manon", "Sofia", "Clara", "Ava", "Maya", "Lina", "Eya", "Asma", "Dorra", "Farah"]
FIRST_M = ["Youssef", "Omar", "Karim", "Mehdi", "Aziz", "Hamza", "Amine", "Walid", "Skander", "Bilel", "Lucas", "Hugo",
           "Louis", "Nathan", "Adam", "Elias", "Leo", "Noah", "Rayan", "Malek", "Fares", "Anis", "Seif", "Tarek"]
LAST = ["Ben Ali", "Trabelsi", "Haddad", "Gharbi", "Jaziri", "Mansour", "Bouazizi", "Chebbi", "Kefi", "Riahi", "Saidi",
        "Mejri", "Ayari", "Hamdi", "Zouari", "Ferchichi", "Martin", "Bernard", "Dubois", "Petit", "Durand", "Moreau",
        "Laurent", "Simon", "Michel", "Lefebvre", "Garcia", "Rossi", "Novak", "Silva", "Khalil", "Nasser"]


def generate_directory(people: list[dict], seed: int) -> list[dict]:
    rng = random.Random(seed * 7919 + 1)
    rows, used = [], set()
    for p in people:
        pool = FIRST_F if p["gender"] == "F" else FIRST_M if p["gender"] == "M" else FIRST_F + FIRST_M
        first, last = rng.choice(pool), rng.choice(LAST)
        handle = f"{first}.{last}".lower().replace(" ", "")
        email, n = f"{handle}@northwind.example.test", 2
        while email in used:  # keep addresses unique
            email, n = f"{handle}{n}@northwind.example.test", n + 1
        used.add(email)
        rows.append({"employee_id": p["employee_id"], "first_name": first, "last_name": last, "email": email})
    return rows


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row.get(k) is None else row[k]) for k in fields})


def summarise(people: list[dict], training: list[dict], engagement: list[dict], as_of: date) -> list[str]:
    """Self-check of the planted stories, using the definitions in backend/services/analytics/README.md."""
    def headcount(day: date, **f: str) -> int:
        return sum(1 for p in people if active_on(p, day) and all(p[k] == v for k, v in f.items()))

    def exits(a: date, b: date, **f: str) -> list[dict]:
        return [p for p in people if p["end_date"] and a <= p["end_date"] <= b and all(p[k] == v for k, v in f.items())]

    def rate(a: date, b: date, **f: str) -> float:
        avg = (headcount(a, **f) + headcount(b, **f)) / 2
        return len(exits(a, b, **f)) / avg if avg else 0.0

    qs = quarters((2024, 4), (2026, 3))
    bounds = [(date(y, 3 * q - 2, 1), quarter_end(y, q)) for y, q in qs]
    company_avg = sum(rate(a, b) for a, b in bounds) / len(bounds)
    q2 = (date(2026, 4, 1), date(2026, 6, 30))
    support_q2 = rate(*q2, department="Support")
    reasons = [p["exit_reason"] for p in exits(*q2, department="Support")]
    year = (as_of - timedelta(days=365), as_of)
    annual = {d: rate(*year, department=d) for d in DEPARTMENTS}
    tenure = {d: sum((as_of - p["hire_date"]).days for p in people if p["department"] == d and active_on(p, as_of))
              / 365.25 / max(headcount(as_of, department=d), 1) for d in DEPARTMENTS}
    dept_of = {p["employee_id"]: p["department"] for p in people}
    completion = {d: (sum(r["completed"] == "true" for r in training if dept_of[r["employee_id"]] == d)
                      / max(sum(1 for r in training if dept_of[r["employee_id"]] == d), 1)) for d in DEPARTMENTS}
    contract_rate = {c: rate(*year, contract=c) for c in ("permanent", "fixed_term", "intern")}

    def site_score(site: str) -> float:
        rows = [r for r in engagement if r["site"] == site and r["quarter"] >= "2025Q4"]
        return sum(float(r["score"]) * r["respondents"] for r in rows) / max(sum(r["respondents"] for r in rows), 1)

    def support_eng(quarter: str) -> float:
        rows = [r for r in engagement if r["department"] == "Support" and r["quarter"] == quarter]
        return sum(float(r["score"]) * r["respondents"] for r in rows) / max(sum(r["respondents"] for r in rows), 1)

    return [
        f"(1) Support 2026Q2 attrition {support_q2:.1%} vs company quarterly average {company_avg:.1%} "
        f"({support_q2 / company_avg:.1f}x); {reasons.count('career_growth')}/{len(reasons)} exits career_growth; "
        f"Support engagement 2025Q4 {support_eng('2025Q4'):.2f} -> 2026Q1 {support_eng('2026Q1'):.2f} -> 2026Q2 {support_eng('2026Q2'):.2f}",
        f"(2) 12-month attrition by department: " + ", ".join(f"{d} {r:.1%}" for d, r in sorted(annual.items(), key=lambda t: t[1]))
        + f"; average tenure: " + ", ".join(f"{d} {t:.2f}y" for d, t in sorted(tenure.items(), key=lambda t: -t[1])),
        f"(3) Training completion: " + ", ".join(f"{d} {c:.0%}" for d, c in completion.items()),
        f"(4) 12-month attrition by contract: " + ", ".join(f"{c} {r:.1%}" for c, r in contract_rate.items()),
        f"(5) Engagement (last 4 quarters, respondent-weighted): Remote {site_score('Remote'):.2f}, "
        f"Paris {site_score('Paris'):.2f}, Tunis {site_score('Tunis'):.2f}",
    ]


def generate(seed: int, as_of: date, people_dir: Path, audit_file: Path) -> list[str]:
    rng = random.Random(seed)
    people = generate_employees(rng, as_of)
    engagement = generate_engagement(rng, people)
    training = generate_training(rng, people, as_of)
    people_dir.mkdir(parents=True, exist_ok=True)
    write_csv(people_dir / "employees.csv", people, FIELDS)
    write_csv(people_dir / "engagement.csv", engagement, ["quarter", "department", "site", "score", "response_rate", "respondents"])
    write_csv(people_dir / "training.csv", training, ["employee_id", "course", "hours", "completed"])
    write_csv(people_dir / "open_positions.csv", generate_positions(), ["job_id", "department", "title", "opened_date", "status"])
    # Identified data lives apart from the pseudonymous analytics files; only the HR directory reads it.
    write_csv(people_dir / "directory.csv", generate_directory(people, seed), ["employee_id", "first_name", "last_name", "email"])
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    audit_file.write_text("".join(json.dumps(e) + "\n" for e in generate_audit_events(rng, as_of)), encoding="utf-8")
    active = sum(1 for p in people if active_on(p, as_of))
    return [f"{active} active employees and {len(people) - active} past leavers as of {as_of}; "
            f"{len(training)} training rows; {len(engagement)} engagement rows"] + summarise(people, training, engagement, as_of)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic Northwind Labs people data (fictional).")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--as-of", type=date.fromisoformat, default=DEFAULT_AS_OF)
    parser.add_argument("--out", type=Path, default=PEOPLE_DIR)
    parser.add_argument("--audit-out", type=Path, default=AUDIT_FILE)
    args = parser.parse_args()
    lines = generate(args.seed, args.as_of, args.out, args.audit_out)
    print(f"Wrote {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out} and "
          f"{args.audit_out.relative_to(ROOT) if args.audit_out.is_relative_to(ROOT) else args.audit_out} (synthetic)")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
