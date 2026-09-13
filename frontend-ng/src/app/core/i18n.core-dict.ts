import { CHAT_EN, CHAT_FR } from './i18n/chat.dict';
import { CHROME_EN, CHROME_FR } from './i18n/chrome.dict';
import { COMMON_EN, COMMON_FR } from './i18n/common.dict';

/**
 * Copy needed to render the application shell, authentication, and Ask.
 *
 * The complete catalogue is intentionally loaded after the first screen is
 * usable. Keeping this small prevents unrelated authoring and legacy-product
 * copy from delaying the product's primary entry point.
 */
export const CORE_FR_DICT: Record<string, string> = {
  ...COMMON_FR,
  ...CHROME_FR,
  ...CHAT_FR,
};

export const CORE_EN_DICT: Record<string, string> = {
  ...COMMON_EN,
  ...CHROME_EN,
  ...CHAT_EN,
};
