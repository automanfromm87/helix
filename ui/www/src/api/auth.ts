import { apiClient, type ApiResponse } from './client'

export type UserRole = 'admin' | 'user'

export interface User {
  id: string
  fullname: string
  email: string
  role: UserRole
  is_active: boolean
  created_at: string
  updated_at: string
  last_login_at?: string
}

export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  fullname: string
  email: string
  password: string
}

export interface LoginResponse {
  user: User
  access_token: string
  refresh_token: string
  token_type: string
}

export interface RegisterResponse extends LoginResponse {}

export interface ChangePasswordRequest {
  old_password: string
  new_password: string
}

export interface ChangeFullnameRequest {
  fullname: string
}

export interface RefreshTokenRequest {
  refresh_token: string
}

export interface RefreshTokenResponse {
  access_token: string
  token_type: string
}

export interface AuthStatusResponse {
  authenticated: boolean
  user?: User
  auth_provider: string
}

export interface SendVerificationCodeRequest {
  email: string
}

export interface ResetPasswordRequest {
  email: string
  verification_code: string
  new_password: string
}

export async function login(request: LoginRequest): Promise<LoginResponse> {
  const response = await apiClient.post<ApiResponse<LoginResponse>>('/auth/login', request)
  return response.data.data
}

export async function register(request: RegisterRequest): Promise<RegisterResponse> {
  const response = await apiClient.post<ApiResponse<RegisterResponse>>('/auth/register', request)
  return response.data.data
}

export async function getAuthStatus(): Promise<AuthStatusResponse> {
  const response = await apiClient.get<ApiResponse<AuthStatusResponse>>('/auth/status')
  return response.data.data
}

export async function changePassword(request: ChangePasswordRequest): Promise<{}> {
  const response = await apiClient.post<ApiResponse<{}>>('/auth/change-password', request)
  return response.data.data
}

export async function changeFullname(request: ChangeFullnameRequest): Promise<User> {
  const response = await apiClient.post<ApiResponse<User>>('/auth/change-fullname', request)
  return response.data.data
}

export async function getCurrentUser(): Promise<User> {
  const response = await apiClient.get<ApiResponse<User>>('/auth/me')
  return response.data.data
}

export async function refreshToken(request: RefreshTokenRequest): Promise<RefreshTokenResponse> {
  const response = await apiClient.post<ApiResponse<RefreshTokenResponse>>('/auth/refresh', request)
  return response.data.data
}

export async function logout(): Promise<{}> {
  const response = await apiClient.post<ApiResponse<{}>>('/auth/logout')
  return response.data.data
}

export async function sendVerificationCode(request: SendVerificationCodeRequest): Promise<{}> {
  const response = await apiClient.post<ApiResponse<{}>>('/auth/send-verification-code', request)
  return response.data.data
}

export async function resetPassword(request: ResetPasswordRequest): Promise<{}> {
  const response = await apiClient.post<ApiResponse<{}>>('/auth/reset-password', request)
  return response.data.data
}

export function setAuthToken(token: string): void {
  apiClient.defaults.headers.common.Authorization = `Bearer ${token}`
}

export function clearAuthToken(): void {
  delete apiClient.defaults.headers.common.Authorization
}

export function getStoredToken(): string | null {
  return localStorage.getItem('access_token')
}

export function storeToken(token: string): void {
  localStorage.setItem('access_token', token)
}

export function storeRefreshToken(refreshToken: string): void {
  localStorage.setItem('refresh_token', refreshToken)
}

export function getStoredRefreshToken(): string | null {
  return localStorage.getItem('refresh_token')
}

export function clearStoredTokens(): void {
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
}

export function initializeAuth(): void {
  const token = getStoredToken()
  if (token) setAuthToken(token)
}
