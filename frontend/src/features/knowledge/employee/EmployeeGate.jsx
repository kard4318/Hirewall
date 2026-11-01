// Employee sign-in for the handbook desk (shared staff passcode in this demo)
import { useState } from "react";
import { Wordmark } from "../../scheduling/Wordmark.jsx";
import { knowledgeApi } from "../api.js";

const MESSAGES = {
  401: "That passcode doesn't match.",
  429: "Too many attempts. Wait a minute and try again.",
  503: "Employee sign-in is not configured on the server (EMPLOYEE_PASSCODE).",
};

export function EmployeeGate({ onToken }) {
  const [passcode, setPasscode] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { token } = await knowledgeApi.login(passcode);
      onToken(token);
    } catch (err) {
      setError(MESSAGES[err.status] || "Sign-in failed. Is the backend running?");
      setPasscode("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="gate paper">
      <form className="gate-card" onSubmit={submit}>
        <Wordmark subtitle="Handbook desk" />
        <h1 className="display">Ask the handbook.</h1>
        <p className="gate-lede">Answers come only from company policies, with the exact section quoted.</p>
        <label className="label" htmlFor="staff-passcode">Staff passcode</label>
        <input id="staff-passcode" type="password" autoComplete="current-password" value={passcode}
          onChange={(e) => setPasscode(e.target.value)} autoFocus required />
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="btn btn-primary" disabled={busy || !passcode}>{busy ? "Checking…" : "Open the desk"}</button>
      </form>
    </div>
  );
}
