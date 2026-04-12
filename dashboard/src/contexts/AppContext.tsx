import { createContext, useContext, ReactNode } from 'react';
import { useTheme } from '@/hooks/useTheme';
import { useLanguage } from '@/hooks/useLanguage';
import { useApiToken } from '@/hooks/useApiToken';
import { Language, Translations } from '@/lib/i18n';

interface AppContextType {
  // Theme
  theme: 'light' | 'dark';
  toggleTheme: () => void;
  isDark: boolean;
  // Language
  language: Language;
  setLanguage: (lang: Language) => void;
  toggleLanguage: () => void;
  t: Translations;
  // API Auth
  apiToken: string;
  setApiToken: (token: string) => void;
  clearApiToken: () => void;
  hasApiToken: boolean;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export function AppProvider({ children }: { children: ReactNode }) {
  const themeState = useTheme();
  const languageState = useLanguage();
  const apiTokenState = useApiToken();

  return (
    <AppContext.Provider
      value={{
        ...themeState,
        ...languageState,
        ...apiTokenState,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  const context = useContext(AppContext);
  if (context === undefined) {
    throw new Error('useApp must be used within AppProvider');
  }
  return context;
}
