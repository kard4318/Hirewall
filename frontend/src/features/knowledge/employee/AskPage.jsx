// /ask route: employee passcode gate, then the handbook desk where employees ask policy questions
import { useState } from "react";
import { employeeSession } from "../api.js";
import { AskDesk } from "./AskDesk.jsx";
import { EmployeeGate } from "./EmployeeGate.jsx";
import "../../scheduling/styles/base.css";
import "../../scheduling/styles/hr.css"; // passcode gate styles
import "../styles/knowledge.css";

export function AskPage() {
  const [token, setToken] = useState(() => employeeSession.get());

  const signIn = (value) => {
    employeeSession.set(value);
    setToken(value);
  };
  const signOut = () => {
    employeeSession.clear();
    setToken(null);
  };

  return token ? <AskDesk token={token} onSignOut={signOut} /> : <EmployeeGate onToken={signIn} />;
}
