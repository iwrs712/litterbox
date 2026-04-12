import { useState, useEffect } from 'react';
import { Language, translations, Translations } from '@/lib/i18n';

export function useLanguage() {
  const [language, setLanguage] = useState<Language>(() => {
    const savedLang = localStorage.getItem('language') as Language;
    if (savedLang && (savedLang === 'en' || savedLang === 'zh')) {
      return savedLang;
    }
    // Default to English
    return 'en';
  });

  useEffect(() => {
    localStorage.setItem('language', language);
    document.documentElement.lang = language;
  }, [language]);

  const toggleLanguage = () => {
    setLanguage(prev => prev === 'en' ? 'zh' : 'en');
  };

  const t: Translations = translations[language];

  return {
    language,
    setLanguage,
    toggleLanguage,
    t,
  };
}
