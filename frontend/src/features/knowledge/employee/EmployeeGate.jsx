// Employee sign-in for the handbook desk, with a named employee account
import { useState } from "react";
import { Wordmark } from "../../scheduling/Wordmark.jsx";
import { knowledgeApi } from "../api.js";

const MESSAGES = {
  401: "That username or password doesn't match.",
  422: "Enter your username and password.",
  429: "Too many attempts. Wait a minute and try again.",
  503: "Sign-in is not configured on the server (HR_TOKEN_SECRET).",
};
const LOCKED = "This account is locked after too many wrong passwords. Wait 15 minutes, or ask an HR admin.";

export function EmployeeGate({ onToken }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { token } = await knowledgeApi.login(username.trim(), password);
      onToken(token);
    } catch (err) {
      setError(err.message === "account_locked" ? LOCKED : MESSAGES[err.status] || "Sign-in failed. Is the backend running?");
      setPassword("");
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
        <label className="label" htmlFor="staff-username">Username</label>
        <input id="staff-username" autoComplete="username" autoCapitalize="none" spellCheck={false} value={username}
          onChange={(e) => setUsername(e.target.value)} autoFocus required />
        <label className="label" htmlFor="staff-password">Password</label>
        <input id="staff-password" type="password" autoComplete="current-password" value={password}
          onChange={(e) => setPassword(e.target.value)} required />
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="btn btn-primary" disabled={busy || !username || !password}>
          {busy ? "Checking…" : "Open the desk"}
        </button>
      </form>
    </div>
  );
}
