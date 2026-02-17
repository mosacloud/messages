import { useEffect, useMemo, useRef } from 'react';
import MailHelper from "@/features/utils/mail-helper";

const DATA_URL_SRC_RE = /src="(data:(image\/[\w+.-]+);base64,([^"]+))"/g;

const SAMPLE_SIZE = 32;

/**
 * Build a lightweight fingerprint from a data URL without storing the full
 * multi-MB base64 string: MIME type, base64 length, and a sample of the
 * first and last characters.
 */
const fingerprint = (mime: string, base64: string): string => {
  const head = base64.slice(0, SAMPLE_SIZE);
  const tail = base64.slice(-SAMPLE_SIZE);
  return `${mime}:${base64.length}:${head}:${tail}`;
};

/**
 * Replaces base64 data URLs with lightweight Object URLs in sanitized HTML.
 * This avoids bloating the DOM with large base64 strings (e.g. ~2.6MB per image)
 * while keeping the visual rendering identical.
 *
 * A cache keyed by a lightweight fingerprint ensures unchanged images are
 * reused across renders. Only Object URLs whose image disappeared from the
 * HTML are revoked; all remaining ones are revoked on unmount.
 */
export const useHtmlWithObjectUrls = (
  html: string | null,
): string | null => {
  // Persistent cache: fingerprint → objectUrl
  const cacheRef = useRef<Map<string, string>>(new Map());

  const processedHtml = useMemo(() => {
    if (!html) return null;

    const usedKeys = new Set<string>();
    let imageIndex = 0;

    const result = html.replace(
      DATA_URL_SRC_RE,
      (fullMatch, dataUrl: string, mime: string, base64: string) => {
        const key = fingerprint(mime, base64);
        usedKeys.add(key);

        const cached = cacheRef.current.get(key);
        if (cached) return `src="${cached}"`;

        const file = MailHelper.dataUrlToFile(dataUrl, `sig-img-${imageIndex++}`);
        if (!file) return fullMatch;

        const objectUrl = URL.createObjectURL(file);
        cacheRef.current.set(key, objectUrl);
        return `src="${objectUrl}"`;
      },
    );

    // Revoke Object URLs for images no longer present in the HTML
    for (const [key, objectUrl] of cacheRef.current) {
      if (!usedKeys.has(key)) {
        URL.revokeObjectURL(objectUrl);
        cacheRef.current.delete(key);
      }
    }

    return result;
  }, [html]);

  // Revoke all remaining Object URLs on unmount
  useEffect(() => () => {
    for (const objectUrl of cacheRef.current.values()) {
      URL.revokeObjectURL(objectUrl);
    }
    cacheRef.current.clear();
  }, []);

  return processedHtml;
};
