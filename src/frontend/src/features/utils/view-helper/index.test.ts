import { vi, describe, it, expect, beforeEach } from 'vitest';
import ViewHelper from './index';

describe('ViewHelper', () => {
    const setLocationSearch = (search: string) => {
        Object.defineProperty(window, 'location', {
            value: { search },
            writable: true,
            configurable: true,
        });
    };

    beforeEach(() => {
        setLocationSearch('');
    });

    describe('isTrashedView', () => {
        it('should return true when has_trashed=1 is in search params', () => {
            setLocationSearch('?has_trashed=1');
            expect(ViewHelper.isTrashedView()).toBe(true);
        });

        it('should return true when search contains in:trash', () => {
            setLocationSearch('?search=in:trash');
            expect(ViewHelper.isTrashedView()).toBe(true);
        });

        it('should return false when not in trash view', () => {
            setLocationSearch('?has_active=1');
            expect(ViewHelper.isTrashedView()).toBe(false);
        });

        it('should return false when search params are empty', () => {
            setLocationSearch('');
            expect(ViewHelper.isTrashedView()).toBe(false);
        });
    });

    describe('isSpamView', () => {
        it('should return true when is_spam=1 is in search params', () => {
            setLocationSearch('?is_spam=1');
            expect(ViewHelper.isSpamView()).toBe(true);
        });

        it('should return true when search contains in:spam', () => {
            setLocationSearch('?search=in:spam');
            expect(ViewHelper.isSpamView()).toBe(true);
        });

        it('should return false when not in spam view', () => {
            setLocationSearch('?has_active=1');
            expect(ViewHelper.isSpamView()).toBe(false);
        });

        it('should return false when search params are empty', () => {
            setLocationSearch('');
            expect(ViewHelper.isSpamView()).toBe(false);
        });
    });

    describe('isArchivedView', () => {
        it('should return true when has_archived=1 is in search params', () => {
            setLocationSearch('?has_archived=1');
            expect(ViewHelper.isArchivedView()).toBe(true);
        });

        it('should return true when search contains in:archives', () => {
            setLocationSearch('?search=in:archives');
            expect(ViewHelper.isArchivedView()).toBe(true);
        });

        it('should return false when not in archived view', () => {
            setLocationSearch('?has_active=1');
            expect(ViewHelper.isArchivedView()).toBe(false);
        });

        it('should return false when search params are empty', () => {
            setLocationSearch('');
            expect(ViewHelper.isArchivedView()).toBe(false);
        });
    });

    describe('isSentView', () => {
        it('should return true when has_sender=1 is in search params', () => {
            setLocationSearch('?has_sender=1');
            expect(ViewHelper.isSentView()).toBe(true);
        });

        it('should return true when search contains in:sent', () => {
            setLocationSearch('?search=in:sent');
            expect(ViewHelper.isSentView()).toBe(true);
        });

        it('should return false when not in sent view', () => {
            setLocationSearch('?has_active=1');
            expect(ViewHelper.isSentView()).toBe(false);
        });

        it('should return false when search params are empty', () => {
            setLocationSearch('');
            expect(ViewHelper.isSentView()).toBe(false);
        });
    });

    describe('isDraftsView', () => {
        it('should return true when has_draft=1 is in search params', () => {
            setLocationSearch('?has_draft=1');
            expect(ViewHelper.isDraftsView()).toBe(true);
        });

        it('should return true when search contains in:drafts', () => {
            setLocationSearch('?search=in:drafts');
            expect(ViewHelper.isDraftsView()).toBe(true);
        });

        it('should return false when not in drafts view', () => {
            setLocationSearch('?has_active=1');
            expect(ViewHelper.isDraftsView()).toBe(false);
        });

        it('should return false when search params are empty', () => {
            setLocationSearch('');
            expect(ViewHelper.isDraftsView()).toBe(false);
        });
    });

    describe('server-side rendering', () => {
        it('should return false when window is undefined', () => {
            // Simulate SSR environment by stubbing window as undefined
            vi.stubGlobal('window', undefined);

            expect(ViewHelper.isTrashedView()).toBe(false);
            expect(ViewHelper.isSpamView()).toBe(false);
            expect(ViewHelper.isArchivedView()).toBe(false);
            expect(ViewHelper.isSentView()).toBe(false);
            expect(ViewHelper.isDraftsView()).toBe(false);

            vi.unstubAllGlobals();
        });
    });

    describe('edge cases', () => {
        it('should handle search query with additional text', () => {
            setLocationSearch('?search=in:trash%20hello%20world');
            expect(ViewHelper.isTrashedView()).toBe(true);
        });

        it('should handle multiple search params', () => {
            setLocationSearch('?has_archived=1&other_param=value');
            expect(ViewHelper.isArchivedView()).toBe(true);
        });

        it('should return false when filter value does not match', () => {
            setLocationSearch('?has_trashed=0');
            expect(ViewHelper.isTrashedView()).toBe(false);
        });

        it('should correctly distinguish between different views', () => {
            setLocationSearch('?has_trashed=1');
            expect(ViewHelper.isTrashedView()).toBe(true);
            expect(ViewHelper.isSpamView()).toBe(false);
            expect(ViewHelper.isArchivedView()).toBe(false);
            expect(ViewHelper.isSentView()).toBe(false);
            expect(ViewHelper.isDraftsView()).toBe(false);
        });

        it('should handle URL encoded search params', () => {
            setLocationSearch('?search=in%3Aspam');
            expect(ViewHelper.isSpamView()).toBe(true);
        });
    });
});
