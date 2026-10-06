import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { ThemeProvider } from './context/ThemeContext';
import { I18nProvider } from './i18n/I18nContext';
import './index.css';
import { registerSW } from 'virtual:pwa-register';
import { initSyncEngine } from './lib/syncEngine';

// Register the PWA service worker. autoUpdate means new versions install
// silently in the background; we don't pop a "reload" prompt for field workers.
registerSW({ immediate: true });

// Kick off the background sync engine — drains any queued offline writes
// the moment we're back online.
initSyncEngine();

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ThemeProvider>
      <I18nProvider>
        <App />
      </I18nProvider>
    </ThemeProvider>
  </React.StrictMode>
);
