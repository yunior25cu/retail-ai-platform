/**
 * Auth state — React Context + useReducer.
 * Persisted in localStorage via tokenStore.
 */

import {
  createContext,
  useContext,
  useReducer,
  type Dispatch,
  type ReactNode,
} from "react";
import { tokenStore } from "@/api/client";

export interface AuthUser {
  id: string;
  email: string;
  role: string;
  full_name: string | null;
  tenant_id: number;
  tenant_name?: string | null;  // display name from /auth/me (e.g. "Prolimpio")
  vertical: string;
}

export interface AuthState {
  user: AuthUser | null;
  accessToken: string | null;
  refreshToken: string | null;
  vertical: "retail" | "produccion" | null;
}

type Action =
  | {
      type: "SET_TOKENS";
      payload: {
        accessToken: string;
        refreshToken: string;
        vertical: string;
        tenant_id: number;
        role: string;
      };
    }
  | { type: "SET_USER"; payload: AuthUser }
  | { type: "CLEAR" };

function reducer(state: AuthState, action: Action): AuthState {
  switch (action.type) {
    case "SET_TOKENS":
      tokenStore.setAccess(action.payload.accessToken);
      tokenStore.setRefresh(action.payload.refreshToken);
      return {
        ...state,
        accessToken: action.payload.accessToken,
        refreshToken: action.payload.refreshToken,
        vertical: action.payload.vertical as AuthState["vertical"],
      };
    case "SET_USER":
      return { ...state, user: action.payload };
    case "CLEAR":
      tokenStore.clear();
      return { user: null, accessToken: null, refreshToken: null, vertical: null };
    default:
      return state;
  }
}

const initialState: AuthState = {
  user: null,
  accessToken: tokenStore.getAccess(),
  refreshToken: tokenStore.getRefresh(),
  vertical: null,
};

export const AuthContext = createContext<{
  state: AuthState;
  dispatch: Dispatch<Action>;
} | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  return (
    // eslint-disable-next-line react/jsx-no-constructed-context-values
    <AuthContext.Provider value={{ state, dispatch }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuthStore() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuthStore must be inside AuthProvider");
  return ctx;
}
