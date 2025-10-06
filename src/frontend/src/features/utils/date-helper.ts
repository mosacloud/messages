import { format, isToday, differenceInDays } from 'date-fns';
// @WARN: This import is surely importing to much locales, later we should
// import only the needed locales
import * as locales from 'date-fns/locale';
import i18n from '../i18n/initI18n';

export class DateHelper {
  /**
   * Formats a date string based on how recent it is:
   * - Today: displays time (HH:mm)
   * - Less than 1 month: displays short date (e.g., "3 mars")
   * - Otherwise: displays full date (DD/MM/YYYY)
   *
   * @param dateString - The date string to format
   * @param locale - The locale code (e.g., 'fr', 'en')
   * @returns Formatted date string
   */
  public static formatDate(dateString: string, lng: string = 'en'): string {
    const date = new Date(dateString);
    const daysDifference = differenceInDays(new Date(), date);
    const locale = lng.length > 2 ? lng.split('-')[0] : lng;
    const dateLocale = locales[locale as keyof typeof locales];

    if (isToday(date)) {
      return format(date, 'HH:mm', { locale: dateLocale });
    }

    if (daysDifference < 30) {
      return format(date, 'd MMMM', { locale: dateLocale });
    }

    return format(date, 'dd/MM/yyyy', { locale: dateLocale });
  }

  /**
   * Compute a relative time between a given date and a time reference and
   * return a translation key and a count if needed.
   *
   * For now only past relative time is supported.
   *
   * @param dateString - The date string to format
   * @param timeRef - The time reference to compute the relative time from
   * @returns [translationKey, count]
   */
  public static formatRelativeTime(dateString: string, timeRef: Date | string = new Date()): string {
    const now = timeRef instanceof Date ? timeRef : new Date(timeRef);
    const date = new Date(dateString);
    const diffInSeconds = Math.floor((now.getTime() - date.getTime()) / 1000);

    if (isNaN(diffInSeconds)) {
      return "";
    }

    if (diffInSeconds < 5) {
      return i18n.t("just now");
    }
    else if (diffInSeconds < 60) {
      return i18n.t("less than a minute ago");
    }
    else if (diffInSeconds < 3600) {
      return i18n.t("{{count}} minutes ago", {
        count: Math.floor(diffInSeconds / 60),
        defaultValue_one: "{{count}} minute ago",
        defaultValue_other: "{{count}} minutes ago",
      })
    }
    else if (diffInSeconds < 86400) {
      return i18n.t("{{count}} hours ago", {
          count: Math.floor(diffInSeconds / 3600),
          defaultValue_one: "{{count}} hour ago",
          defaultValue_other: "{{count}} hours ago",
        });
    }
    else {
      return i18n.t("{{count}} days ago", {
        count: Math.floor(diffInSeconds / 86400),
        defaultValue_one: "{{count}} day ago",
        defaultValue_other: "{{count}} days ago",
      });
    }
  }
}
