const USER_ID_KEY = 'hopper_user_id'
const USER_EMAIL_KEY = 'hopper_user_email'

export function getStoredUserId(): number | null {
  const stored = localStorage.getItem(USER_ID_KEY)
  return stored ? parseInt(stored, 10) : null
}

export function setStoredUserId(userId: number) {
  localStorage.setItem(USER_ID_KEY, userId.toString())
}

export function getStoredUserEmail(): string | null {
  return localStorage.getItem(USER_EMAIL_KEY)
}

export function setStoredUserEmail(email: string) {
  localStorage.setItem(USER_EMAIL_KEY, email)
}

export function clearStorage() {
  localStorage.removeItem(USER_ID_KEY)
  localStorage.removeItem(USER_EMAIL_KEY)
}

export function logout() {
  clearStorage()
  window.location.href = '/'
}

