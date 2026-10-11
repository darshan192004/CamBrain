/**
 * Authentication store (Pinia): login, logout, and one-shot session
 * hydration through `GET /auth/me`. Tokens themselves live in the
 * in-memory token module — this store holds only the user projection.
 * @module stores/auth
 */

import { defineStore } from "pinia";
import { get, post } from "../api/client.js";
import { clearTokens, getAccessToken, setTokens } from "../api/token.js";

/**
 * Session state for the dashboard.
 * @returns {object} Pinia store options with user state and auth actions
 */
export const useAuthStore = defineStore("auth", {
  state: () => ({
    /** @type {{user_id: number, username: string, role: string, site_id: number}|null} */
    user: null,
    hydrated: false,
    _hydration: null,
  }),

  getters: {
    /**
     * Active role ("admin" | "viewer"), or null when signed out.
     * @param {object} state current store state
     * @returns {string|null} the role
     */
    role: (state) => state.user?.role ?? null,
    /**
     * Whether a session is established.
     * @param {object} state current store state
     * @returns {boolean} true when a user is loaded
     */
    isAuthenticated: (state) => state.user !== null,
    /**
     * Admin-only convenience for guards and the sidebar.
     * @returns {boolean} true for admins
     */
    isAdmin() {
      return this.role === "admin";
    },
  },

  actions: {
    /**
     * Exchange credentials for tokens and load the identity.
     * @param {string} username login name
     * @param {string} password password (never logged, never stored)
     * @returns {Promise<object>} the /auth/me projection
     */
    async login(username, password) {
      const pair = await post(
        "/auth/login",
        { username, password },
        { auth: false },
      );
      setTokens(pair);
      try {
        this.user = await get("/auth/me");
      } catch (err) {
        clearTokens();
        this.user = null;
        throw err;
      }
      this.hydrated = true;
      return this.user;
    },

    /**
     * Load the current session once per page load; safe to await from
     * concurrent guard runs (single-flight).
     * @returns {Promise<void>} resolves when hydration has settled
     */
    ensureHydrated() {
      if (this.hydrated) {
        return Promise.resolve();
      }
      if (!this._hydration) {
        this._hydration = this.hydrate().finally(() => {
          this._hydration = null;
        });
      }
      return this._hydration;
    },

    /**
     * Ask the API who we are; any failure means the session is gone.
     * @returns {Promise<void>} resolves after the attempt settles
     */
    async hydrate() {
      try {
        if (!getAccessToken()) {
          this.user = null;
          return;
        }
        this.user = await get("/auth/me");
      } catch {
        clearTokens();
        this.user = null;
      } finally {
        this.hydrated = true;
      }
    },

    /**
     * Revoke the session server-side and drop local state. Server errors
     * are ignored — the result is the same either way.
     * @returns {Promise<void>} resolves when local state is cleared
     */
    async logout() {
      try {
        await post("/auth/logout");
      } catch {
        // Session may already be gone; clearing local state is the goal.
      }
      clearTokens();
      this.user = null;
      this.hydrated = true;
    },
  },
});
