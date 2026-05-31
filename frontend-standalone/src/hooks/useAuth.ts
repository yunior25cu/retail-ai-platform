/**
 * useAuth — authentication hook.
 *
 * Validates token on mount via GET /api/v1/auth/me.
 * Exposes login(), logout(), user, isAuthenticated.
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type LoginPayload } from "@/api/client";
import { useAuthStore, type AuthUser } from "@/store/auth.tsx";

export function useAuth() {
  const { state, dispatch } = useAuthStore();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(!!state.accessToken && !state.user);

  // Validate token on mount if we have one but no user loaded yet
  useEffect(() => {
    if (!state.accessToken || state.user) {
      setLoading(false);
      return;
    }
    api
      .getMe()
      .then((u) => {
        const user: AuthUser = {
          id: u.id,
          email: u.email,
          role: u.role,
          full_name: u.full_name,
          tenant_id: u.tenant_id,
          vertical: state.vertical ?? "retail",
        };
        dispatch({ type: "SET_USER", payload: user });
      })
      .catch(() => {
        dispatch({ type: "CLEAR" });
      })
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const login = useCallback(
    async (payload: LoginPayload) => {
      const tokens = await api.login(payload);
      dispatch({
        type: "SET_TOKENS",
        payload: {
          accessToken: tokens.access_token,
          refreshToken: tokens.refresh_token,
          vertical: tokens.vertical,
          tenant_id: tokens.tenant_id,
          role: tokens.role,
        },
      });
      const me = await api.getMe();
      dispatch({
        type: "SET_USER",
        payload: {
          id: me.id,
          email: me.email,
          role: me.role,
          full_name: me.full_name,
          tenant_id: me.tenant_id,
          vertical: tokens.vertical,
        },
      });
      navigate("/");
    },
    [dispatch, navigate]
  );

  const logout = useCallback(async () => {
    await api.logout();
    dispatch({ type: "CLEAR" });
    navigate("/login");
  }, [dispatch, navigate]);

  return {
    user: state.user,
    isAuthenticated: !!state.accessToken && !!state.user,
    loading,
    login,
    logout,
    accessToken: state.accessToken,
    vertical: state.vertical,
  };
}
