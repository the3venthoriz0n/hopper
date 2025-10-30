import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
})

export interface Destination {
  id: number
  platform: string
  enabled: boolean
}

export interface Video {
  id: number
  filename: string
  title: string | null
  description: string | null
  privacy: string
  status: string
  scheduled_time: string | null
  upload_destinations: number[]
  created_at: string
}

// Auth
export async function getYouTubeAuthUrl() {
  const response = await api.get('/auth/youtube/url')
  return response.data
}

export async function completeYouTubeAuth(code: string, email: string) {
  const response = await api.post('/auth/youtube/callback', null, {
    params: { code, user_email: email }
  })
  return response.data
}

// Destinations
export async function getUserDestinations(userId: number): Promise<Destination[]> {
  const response = await api.get(`/destinations/user/${userId}`)
  return response.data
}

export async function toggleDestination(destinationId: number, enabled: boolean) {
  const response = await api.patch(`/destinations/${destinationId}`, { enabled })
  return response.data
}

export async function removeDestination(destinationId: number) {
  const response = await api.delete(`/destinations/${destinationId}`)
  return response.data
}

// Videos
export async function getUserVideos(userId: number): Promise<Video[]> {
  const response = await api.get(`/videos/user/${userId}`)
  return response.data
}

export async function uploadVideo(userId: number, file: File) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('user_id', userId.toString())
  
  const response = await api.post('/videos/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
  return response.data
}

export async function updateVideo(
  videoId: number,
  data: {
    title?: string
    description?: string
    privacy?: string
    scheduled_time?: string | null
    upload_destinations?: number[]
  }
) {
  const response = await api.patch(`/videos/${videoId}`, data)
  return response.data
}

export async function deleteVideo(videoId: number) {
  const response = await api.delete(`/videos/${videoId}`)
  return response.data
}

export async function triggerUpload(videoId: number) {
  const response = await api.post(`/videos/${videoId}/upload`)
  return response.data
}

export default api

