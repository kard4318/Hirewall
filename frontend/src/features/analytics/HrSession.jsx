// HR session context shared by the analytics pages: the token and a sign-out for expired sessions
import { createContext, useContext } from "react";

export const HrSessionContext = createContext({ token: null, signOut: () => {} });

export function useHrSession() {
  return useContext(HrSessionContext);
}
