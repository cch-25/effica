export const PROFILE_UPDATED_KEY = "effica:profile-updated";

export function notifyProfileUpdated() {
  try {
    // Only a change marker crosses tabs; questionnaire answers stay on the server.
    localStorage.setItem(PROFILE_UPDATED_KEY, String(Date.now()));
  } catch {
    // Storage may be unavailable in a restricted browser. Saving still succeeds.
  }
}
