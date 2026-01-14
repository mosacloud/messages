import { SearchHelper } from "../search-helper";
import { MAILBOX_FOLDERS } from "@/features/layouts/components/mailbox-panel/components/mailbox-list";

// Type for the union of all folder id values, generated from MAILBOX_FOLDERS
export type ViewName = ReturnType<typeof MAILBOX_FOLDERS>[number]['id'];

class ViewHelper {
    #isView(viewName: ViewName): boolean {
        if (typeof window === 'undefined') return false;

        const searchParams = new URLSearchParams(window.location.search);
        const folder = MAILBOX_FOLDERS().find((folder) => folder.id === viewName);
        if (!folder) throw new Error(`${viewName} folder not found. Invalid folder id "${viewName}".`);

        const matchViewFilters = Object.entries(folder.filter || {}).every(([key, value]) => searchParams.get(key) === value);
        if (matchViewFilters) return true;

        const matchSearchParams = folder.searchable && SearchHelper.parseSearchQuery(searchParams.get('search') || '')?.in === viewName;
        return matchSearchParams;
    }

    static isTrashedView() {
        return new ViewHelper().#isView('trash');
    }

    static isSpamView() {
        return new ViewHelper().#isView('spam');
    }

    static isArchivedView() {
        return new ViewHelper().#isView('archives');
    }

    static isSentView() {
        return new ViewHelper().#isView('sent');
    }

    static isDraftsView() {
        return new ViewHelper().#isView('drafts');
    }
}

export default ViewHelper;
