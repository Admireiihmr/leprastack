import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { DICTIONARIES, LANGUAGES } from './translations';

const I18nContext = createContext(null);

export function I18nProvider({ children }) {
  const [lang, setLang] = useState(() => localStorage.getItem('lang') || 'en');

  useEffect(() => {
    localStorage.setItem('lang', lang);
    document.documentElement.setAttribute('lang', lang);
  }, [lang]);

  const t = useCallback(
    (key, fallback) => {
      const dict = DICTIONARIES[lang] || DICTIONARIES.en;
      return dict[key] || DICTIONARIES.en[key] || fallback || key;
    },
    [lang]
  );

  return (
    <I18nContext.Provider value={{ lang, setLang, t, languages: LANGUAGES }}>
      {children}
    </I18nContext.Provider>
  );
}

export const useTranslation = () => useContext(I18nContext);
