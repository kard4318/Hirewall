// HR sign-in: a named account, so every decision in the ledger carries the person's name
import { useState } from "react";
import { hrApi } from "../api.js";
import { Wordmark } from "../Wordmark.jsx";

const MESSAGES = {
  401: "That username or password doesn't match.",
  422: "Enter your username and password.",
  429: "Too many attempts. Wait a minute and try again.",
  503: "Sign-in is not configured on the server (HR_TOKEN_SECRET).",
};
const LOCKED = "This account is locked after too many wrong passwords. Wait 15 minutes, or ask an HR admin.";

export function PasscodeGate({ onToken }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { token } = await hrApi.login(username.trim(), password);
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
        <Wordmark subtitle="People office" />
        <h1 className="display">The ledger is closed.</h1>
        <p className="gate-lede">Every decision here carries the name of the person who made it. Sign in with your own account.</p>
        <label className="label" htmlFor="hr-username">Username</label>
        <input id="hr-username" autoComplete="username" autoCapitalize="none" spellCheck={false} value={username}
          onChange={(e) => setUsername(e.target.value)} autoFocus required />
        <label className="label" htmlFor="hr-password">Password</label>
        <input id="hr-password" type="password" autoComplete="current-password" value={password}
          onChange={(e) => setPassword(e.target.value)} required />
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="btn btn-primary" disabled={busy || !username || !password}>
          {busy ? "Checking…" : "Open the ledger"}
        </button>
      </form>
    </div>
  );
}
