import React from 'react';
import { useTranslation } from 'react-i18next';
import { Languages } from 'lucide-react';
import { SUPPORTED_LANGUAGES, LANGUAGE_STORAGE_KEY } from '../i18n/config';

interface LanguageSwitcherProps {
  dark?: boolean;
}

export default function LanguageSwitcher({ dark = true }: LanguageSwitcherProps) {
  const { i18n } = useTranslation();

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const lang = e.target.value;
    i18n.changeLanguage(lang);
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
  };

  return (
    <div
      className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md border ${
        dark ? 'bg-white/10 border-white/10 text-white' : 'bg-white border-gray-200 text-[#115e59]'
      }`}
    >
      <Languages className="w-3.5 h-3.5 shrink-0 opacity-80" />
      <select
        value={i18n.resolvedLanguage || i18n.language}
        onChange={handleChange}
        className={`bg-transparent text-xs font-semibold outline-none cursor-pointer ${dark ? '[&>option]:text-black' : ''}`}
        aria-label="Language"
      >
        {SUPPORTED_LANGUAGES.map((l) => (
          <option key={l.code} value={l.code}>
            {l.label}
          </option>
        ))}
      </select>
    </div>
  );
}
