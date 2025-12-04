import { useTranslation } from "react-i18next";

/**
 * This component is used to display a preview of a thread when it is being dragged.
 * It aims to be rendered within the portal dedicated to drag preview '#drag-preview-container''
 * Take a look at `_document.tsx`
 */
export const ThreadDragPreview = ({ count }: { count: number }) => {
    const { t } = useTranslation();
    return (
        <span className="thread-drag-preview">
            {t('{{count}} threads selected', {
                count: count,
                defaultValue_one: "{{count}} thread selected",
                defaultValue_other: "{{count}} threads selected"
            })}
        </span>
    )
}
