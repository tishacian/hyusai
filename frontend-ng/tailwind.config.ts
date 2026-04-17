import type { Config } from 'tailwindcss';

export default {
  content: ['./src/**/*.{html,ts}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#e0fbff',
          100: '#b8f5ff',
          200: '#80ecff',
          300: '#33dcfd',
          400: '#0fc9ee',
          500: '#00bcd4',
          600: '#00a0b4',
          700: '#008092',
          800: '#006576',
          900: '#004a56',
        },
        accent: {
          DEFAULT: '#00bcd4',
          violet: '#8b5cf6',
          indigo: '#6366f1',
        },
        success: {
          DEFAULT: '#10b981',
          bg: 'rgba(16, 185, 129, 0.12)',
        },
        warning: {
          DEFAULT: '#f59e0b',
          bg: 'rgba(245, 158, 11, 0.12)',
        },
        danger: {
          DEFAULT: '#ef4444',
          bg: 'rgba(239, 68, 68, 0.12)',
        },
        info: {
          DEFAULT: '#6366f1',
          bg: 'rgba(99, 102, 241, 0.12)',
        },
        surface: {
          light: '#f8fafc',
          dark: '#0a0e1a',
          'card-light': '#ffffff',
          'card-dark': '#111827',
          'raised-dark': '#1a1f2e',
          'muted-dark': '#0f1420',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      borderRadius: {
        xs: '3px',
        sm: '4px',
        DEFAULT: '6px',
        md: '6px',
        lg: '8px',
        xl: '12px',
      },
      backgroundImage: {
        'gradient-brand': 'linear-gradient(135deg, #00bcd4 0%, #6366f1 50%, #8b5cf6 100%)',
        'gradient-brand-soft': 'linear-gradient(135deg, rgba(0,188,212,0.15) 0%, rgba(139,92,246,0.15) 100%)',
        'gradient-mesh':
          'radial-gradient(at 20% 10%, rgba(0,188,212,0.18) 0px, transparent 45%), radial-gradient(at 80% 0%, rgba(139,92,246,0.15) 0px, transparent 40%), radial-gradient(at 10% 80%, rgba(99,102,241,0.12) 0px, transparent 45%), radial-gradient(at 85% 85%, rgba(0,188,212,0.10) 0px, transparent 40%)',
      },
      boxShadow: {
        glow: '0 0 24px rgba(0, 188, 212, 0.45)',
        'glow-sm': '0 0 12px rgba(0, 188, 212, 0.35)',
        'inset-border': 'inset 0 0 0 1px rgba(255, 255, 255, 0.06)',
        elevated: '0 8px 24px -4px rgba(0, 0, 0, 0.4), 0 2px 8px -2px rgba(0, 0, 0, 0.3)',
      },
      keyframes: {
        'gradient-shift': {
          '0%, 100%': { backgroundPosition: '0% 50%' },
          '50%': { backgroundPosition: '100% 50%' },
        },
        'pulse-glow': {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(0, 188, 212, 0.55)' },
          '50%': { boxShadow: '0 0 0 8px rgba(0, 188, 212, 0)' },
        },
        'slide-up': {
          '0%': { transform: 'translateY(8px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-400px 0' },
          '100%': { backgroundPosition: '400px 0' },
        },
        'underline-flow': {
          '0%, 100%': { transform: 'translateX(-100%)' },
          '50%': { transform: 'translateX(100%)' },
        },
      },
      animation: {
        'gradient-shift': 'gradient-shift 12s ease infinite',
        'pulse-glow': 'pulse-glow 2s ease-in-out infinite',
        'slide-up': 'slide-up 0.25s ease-out',
        'fade-in': 'fade-in 0.3s ease-out',
        shimmer: 'shimmer 1.8s linear infinite',
        'underline-flow': 'underline-flow 6s ease-in-out infinite',
      },
      backdropBlur: {
        xs: '2px',
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
} satisfies Config;
