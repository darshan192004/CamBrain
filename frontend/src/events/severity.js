/**
 * Severity → Tailwind token class for event badges. The badge text always
 * accompanies the colour (design §11: colour is never the only signal).
 * @module events/severity
 */

/** @type {Record<string, string>} severity value → text token class */
export const SEVERITY_CLASS = {
  critical: "text-alert-critical",
  warning: "text-alert-warning",
  info: "text-text-secondary",
};

/**
 * Class for a severity, falling back to muted text for unknown values.
 * @param {string} severity event severity
 * @returns {string} Tailwind class string
 */
export function severityClass(severity) {
  return SEVERITY_CLASS[severity] ?? "text-text-secondary";
}
