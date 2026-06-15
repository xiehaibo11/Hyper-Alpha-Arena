// Site branding for this deployment. Set via Vite env at build/deploy time:
//   VITE_SITE_NAME, VITE_SITE_URL, VITE_SITE_LOGO
export const SITE_NAME = (import.meta.env.VITE_SITE_NAME as string) || 'Hyper Alpha Arena'
export const SITE_URL = (import.meta.env.VITE_SITE_URL as string) || '/'
export const SITE_LOGO = (import.meta.env.VITE_SITE_LOGO as string) || '/static/logo_app.png'
