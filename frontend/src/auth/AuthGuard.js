/**
 * Route access rules, extracted from the router so they are unit-testable
 * without a browser history (design §3 information architecture, §7 roles).
 * @module auth/AuthGuard
 */

/**
 * Decide whether a navigation may proceed.
 *
 * Order: hydrate the session once, bounce signed-in users away from
 * /login, bounce signed-out users to /login, then apply per-route roles
 * (admin-only settings redirect home rather than 403 — the API is the
 * authority; the UI simply never offers the door).
 * @param {object} to vue-router route being entered
 * @param {object} auth Pinia auth store instance
 * @returns {Promise<string|true>} redirect path, or true to allow
 */
export async function authGuard(to, auth) {
  await auth.ensureHydrated();
  if (to.meta.public) {
    return auth.isAuthenticated ? "/cameras" : true;
  }
  if (!auth.isAuthenticated) {
    return "/login";
  }
  if (to.meta.roles && !to.meta.roles.includes(auth.role)) {
    return "/cameras";
  }
  return true;
}
