import { Attachment } from "@/features/api/gen/models";
import { CALC_EXTENSIONS, MIME_TO_CATEGORY, MIME_TO_FORMAT_TRANSLATION_KEY, MIME_TO_ICON, MIME_TO_ICON_MINI, MimeCategory } from "./constants";
import { getBlobDownloadRetrieveUrl } from "@/features/api/gen/blob/blob";
import { getRequestUrl } from "@/features/api/utils";
import { DriveFile } from "@/features/forms/components/message-form/drive-attachment-picker";


/**
 * An helper class to handle attachments (Extract mime category, get icon, etc.)
 */
export class AttachmentHelper {
    /**
     * Get the extension of an attachment from its name
     */
    static getExtension(attachment: DriveFile | Attachment | File) {
        if (!attachment.name) return undefined;

        return attachment.name
                .split(".")
                .findLast((_, index) => index !== 0);
    }

    /**
     * Get the mime category of an attachment
     */
    static getMimeCategory(attachment: DriveFile | Attachment | File): MimeCategory {
        // Special case: some calc files have application/zip mimetype. For those we should check their extension too.
        // Otherwise they will be shown as zip files.
        const extension = AttachmentHelper.getExtension(attachment);
        if (
            attachment.type === "application/zip" &&
            extension && CALC_EXTENSIONS.includes(extension)
        ) {
            return MimeCategory.CALC;
        }
        if (MIME_TO_CATEGORY.hasOwnProperty(attachment.type)) return MIME_TO_CATEGORY[attachment.type];
        if (attachment.type.startsWith("image/")) return MimeCategory.IMAGE;
        if (attachment.type.startsWith("audio/")) return MimeCategory.AUDIO;
        if (attachment.type.startsWith("video/")) return MimeCategory.VIDEO;
        return MimeCategory.OTHER;
    }

    /**
     * Get the icon of an attachment
     */
    static getIcon(attachment: DriveFile | Attachment | File, mini: boolean = false) {
        const category = AttachmentHelper.getMimeCategory(attachment);
        return mini ? MIME_TO_ICON_MINI[category] : MIME_TO_ICON[category];
    }

    /**
     * Get the format translation key of an attachment
     */
    static getFormatTranslationKey(attachment: DriveFile | Attachment | File) {
        const category = AttachmentHelper.getMimeCategory(attachment);
        return MIME_TO_FORMAT_TRANSLATION_KEY[category];
    };

    /**
     * Build the download url of an attachment blob
     */
    static getDownloadUrl(attachment: DriveFile | Attachment) {
        if ('blobId' in attachment) {
            return getRequestUrl(getBlobDownloadRetrieveUrl(attachment.blobId));
        }
        return attachment.url;
    }

    static getFormattedSize(size: number, language: string = 'en') {
        // Determine the appropriate unit using binary (1024) calculation
        const units: Array<{ divisor: number; unit: Intl.NumberFormatOptions['unit'] }> = [
            { divisor: 1024 ** 4, unit: 'terabyte' },
            { divisor: 1024 ** 3, unit: 'gigabyte' },
            { divisor: 1024 ** 2, unit: 'megabyte' },
            { divisor: 1024, unit: 'kilobyte' },
            { divisor: 1, unit: 'byte' },
        ];

        for (const { divisor, unit } of units) {
            if (size >= divisor) {
                const value = size / divisor;
                const formatter = new Intl.NumberFormat(language, {
                    notation: "compact",
                    style: "unit",
                    unit: unit,
                    unitDisplay: "narrow",
                });
                return formatter.format(value);
            }
        }

        // Fallback for 0 bytes
        const formatter = new Intl.NumberFormat(language, {
            notation: "compact",
            style: "unit",
            unit: "byte",
            unitDisplay: "narrow",
        });
        return formatter.format(size);
    }

    static getFormattedTotalSize(attachments: readonly (DriveFile | Attachment | File)[], language: string = 'en') {
        const totalSize = attachments.reduce((acc, attachment) => acc + attachment.size, 0);
        return AttachmentHelper.getFormattedSize(totalSize, language);
    }
}
