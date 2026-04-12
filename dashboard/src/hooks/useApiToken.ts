import { useEffect, useState } from 'react';
import { apiClient } from '@/lib/api';

const API_BEARER_TOKEN_KEY = 'apiBearerToken';

export function useApiToken() {
  const [apiToken, setApiTokenState] = useState<string>(() => {
    const token = localStorage.getItem(API_BEARER_TOKEN_KEY) ?? '';
    apiClient.setBearerToken(token);
    return token;
  });

  useEffect(() => {
    const normalizedToken = apiToken.trim();
    apiClient.setBearerToken(normalizedToken);

    if (normalizedToken) {
      localStorage.setItem(API_BEARER_TOKEN_KEY, normalizedToken);
      return;
    }

    localStorage.removeItem(API_BEARER_TOKEN_KEY);
  }, [apiToken]);

  const setApiToken = (token: string) => {
    setApiTokenState(token);
  };

  const clearApiToken = () => {
    setApiTokenState('');
  };

  return {
    apiToken,
    setApiToken,
    clearApiToken,
    hasApiToken: apiToken.trim().length > 0,
  };
}
