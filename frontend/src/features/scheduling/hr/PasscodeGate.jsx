// HR passcode gate: exchanges the office passcode for a short-lived HR token
import { useState } from "react";
import { hrApi } from "../api.js";
import { Wordmark } from "../Wordmark.jsx";

const MESSAGES = {
  401: "That passcode doesn't match.",
  429: "Too many attempts. Wait a minute and try again.",
  503: "HR sign-in is not configured on the server (HR_PASSCODE / HR_TOKEN_SECRET).",
};

export function PasscodeGate({ onToken }) {
  const [passcode, setPasscode] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { token } = await hrApi.login(passcode);
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
        <Wordmark subtitle="People office" />
        <h1 className="display">The ledger is closed.</h1>
        <p className="gate-lede">Every decision here carries a human stamp. Enter the office passcode to open it.</p>
        <label className="label" htmlFor="passcode">Office passcode</label>
        <input
          id="passcode"
          type="password"
          autoComplete="current-password"
          value={passcode}
          onChange={(e) => setPasscode(e.target.value)}
          autoFocus
          required
        />
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="btn btn-primary" disabled={busy || !passcode}>
          {busy ? "Checking…" : "Open the ledger"}
        </button>
      </form>
    </div>
  );
}
