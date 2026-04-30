import type { User, UserRole } from '@/api/auth'

export function getUserDisplayName(user: User | null): string {
  if (!user) return 'Guest'
  return user.fullname || user.email || 'Unknown User'
}

export function getRoleDisplayName(role: UserRole): string {
  const roleNames: Record<UserRole, string> = {
    admin: 'Administrator',
    user: 'User',
  }
  return roleNames[role] || role
}

export function getUserAccountStatus(user: User | null): {
  isValid: boolean
  isActive: boolean
  needsAttention: boolean
  message?: string
} {
  if (!user) {
    return {
      isValid: false,
      isActive: false,
      needsAttention: true,
      message: 'No user data available',
    }
  }
  if (!user.is_active) {
    return {
      isValid: false,
      isActive: false,
      needsAttention: true,
      message: 'Account is deactivated',
    }
  }
  return { isValid: true, isActive: true, needsAttention: false }
}

export function formatUserDate(dateString: string): string {
  try {
    const date = new Date(dateString)
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return 'Invalid date'
  }
}

export function getUserAvatar(user: User | null): { type: 'initials' | 'url'; value: string } {
  if (!user) return { type: 'initials', value: 'G' }
  const name = user.fullname || user.email || 'U'
  const initials = name
    .split(/[\s@]/)
    .map((part) => part.charAt(0).toUpperCase())
    .slice(0, 2)
    .join('')
  return { type: 'initials', value: initials || 'U' }
}

export function validateUserInput(data: {
  fullname?: string
  email?: string
  password?: string
}): { isValid: boolean; errors: Record<string, string> } {
  const errors: Record<string, string> = {}

  if (data.fullname !== undefined) {
    if (!data.fullname || data.fullname.trim().length < 2) {
      errors.fullname = 'Full name must be at least 2 characters long'
    } else if (data.fullname.trim().length > 100) {
      errors.fullname = 'Full name must be less than 100 characters'
    }
  }

  if (data.email !== undefined) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
    if (!data.email || !emailRegex.test(data.email)) {
      errors.email = 'Please enter a valid email address'
    }
  }

  if (data.password !== undefined) {
    if (!data.password || data.password.length < 6) {
      errors.password = 'Password must be at least 6 characters long'
    }
  }

  return { isValid: Object.keys(errors).length === 0, errors }
}
