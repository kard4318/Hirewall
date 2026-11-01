// Landing page at /: one box per part of the product (HR dashboard, employee handbook, candidate booking, open positions)
import { Link } from "react-router-dom";
import { Wordmark } from "../scheduling/Wordmark.jsx";
import "../scheduling/styles/base.css";
import "./home.css";

const PAGES = [
  {
    to: "/hr",
    path: "/hr",
    title: "HR dashboard",
    text: "Screened candidates per job, interview invitations, the HR calendar, and the questions employees ask.",
    who: "HR · office passcode",
  },
  {
    to: "/ask",
    path: "/ask",
    title: "Employee handbook",
    text: "Employees ask policy questions; answers come only from company documents, with the sections cited.",
    who: "Employees · staff passcode",
  },
  {
    to: "/candidate",
    path: "/candidate?token=…",
    title: "Candidate booking",
    text: "Candidates chat with the scheduling assistant and book an interview. Opens only from the personal link HR sends.",
    who: "Candidates · invitation link (invite one from /hr)",
  },
  {
    to: "/jobs",
    path: "/jobs",
    title: "Open positions",
    text: "Applicants read the published offers and apply with a CV and an optional cover letter.",
    who: "Applicants · public",
  },
];

export function HomePage() {
  return (
    <div className="home paper">
      <header className="home-head">
        <Wordmark subtitle="Northwind Labs" />
        <h1 className="display">The agent executes, the human decides.</h1>
        <p className="home-lede">Pick a door.</p>
      </header>
      <nav className="home-grid" aria-label="Pages">
        {PAGES.map((page, i) => (
          <Link key={page.to} to={page.to} className="home-box" style={{ "--i": i }}>
            <span className="label">{page.path}</span>
            <span className="home-title">{page.title}</span>
            <span className="home-text">{page.text}</span>
            <span className="home-who">{page.who}</span>
          </Link>
        ))}
      </nav>
    </div>
  );
}
