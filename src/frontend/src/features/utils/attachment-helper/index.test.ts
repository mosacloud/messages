import { AttachmentHelper } from './index';
import { Attachment } from '@/features/api/gen/models';
import { DriveFile } from '@/features/forms/components/message-form/drive-attachment-picker';

describe("AttachmentHelper", () => {
    describe("getRequestUrl", () => {
        beforeEach(() => {
            delete (global as any).window;
        });

        it("should return undefined if window is not defined", () => {
            expect(AttachmentHelper.getRequestUrl("https://example.com")).toBeUndefined();
        });

        it("should return the same URL if window location origin matches", () => {
            (global as any).window = { location: { origin: "https://example.com" } };
            expect(AttachmentHelper.getRequestUrl("https://example.com/path")).toBe("https://example.com/path");
        });

        it("should return the same URL if NEXT_PUBLIC_API_ORIGIN is not set", () => {
            (global as any).window = { location: { origin: "https://frontend.com" } };
            delete process.env.NEXT_PUBLIC_API_ORIGIN;

            expect(AttachmentHelper.getRequestUrl("https://api.com/path")).toBe("https://api.com/path");
        });

        it("should replace origin with NEXT_PUBLIC_API_ORIGIN if different", () => {
            (global as any).window = { location: { origin: "https://frontend.com" } };
            process.env.NEXT_PUBLIC_API_ORIGIN = "https://backend.com";

            expect(AttachmentHelper.getRequestUrl("https://api.com/path")).toBe("https://backend.com/path");
        });
    });

    describe("getDisplayName", () => {
        it("should return the name property", () => {
            const attachment: Attachment = { name: "file.txt", blobId: "123", size: 100, state: "idle" };
            expect(AttachmentHelper.getDisplayName(attachment)).toBe("file.txt");
        });
    });

    describe("getSize", () => {
        it("should return the size property", () => {
            const attachment: Attachment = { name: "file.txt", blobId: "123", size: 1024, state: "idle" };
            expect(AttachmentHelper.getSize(attachment)).toBe(1024);
        });
    });

    describe("getMimeType", () => {
        it("should return the mime type if available", () => {
            const attachment: Attachment = { name: "file.txt", blobId: "123", size: 100, mimeType: "text/plain", state: "idle" };
            expect(AttachmentHelper.getMimeType(attachment)).toBe("text/plain");
        });

        it("should return undefined if mime type is not available", () => {
            const attachment: Attachment = { name: "file.txt", blobId: "123", size: 100, state: "idle" };
            expect(AttachmentHelper.getMimeType(attachment)).toBeUndefined();
        });
    });

    describe("isImage", () => {
        it("should return true for image mime types", () => {
            const attachment: Attachment = { name: "image.png", blobId: "123", size: 100, mimeType: "image/png", state: "idle" };
            expect(AttachmentHelper.isImage(attachment)).toBe(true);
        });

        it("should return false for non-image mime types", () => {
            const attachment: Attachment = { name: "file.txt", blobId: "123", size: 100, mimeType: "text/plain", state: "idle" };
            expect(AttachmentHelper.isImage(attachment)).toBe(false);
        });

        it("should return false if mime type is not available", () => {
            const attachment: Attachment = { name: "file.txt", blobId: "123", size: 100, state: "idle" };
            expect(AttachmentHelper.isImage(attachment)).toBe(false);
        });
    });

    describe("getUrl", () => {
        const getRequestUrl = jest.spyOn(AttachmentHelper, 'getRequestUrl');
        const getBlobDownloadRetrieveUrl = require('@/features/api/gen/blob/blob').getBlobDownloadRetrieveUrl;

        beforeEach(() => {
            jest.clearAllMocks();
        });

        it("should return the url property if it exists on a DriveFile", () => {
            const driveFile: DriveFile = { name: "file.txt", size: 100, url: "https://drive.com/file.txt" };
            expect(AttachmentHelper.getUrl(driveFile)).toBe("https://drive.com/file.txt");
        });

        it("should construct URL from blobId if url property doesn't exist", () => {
            const attachment: Attachment = { name: "file.txt", blobId: "123", size: 100, state: "idle" };
            const mockUrl = "https://api.com/blob/123";

            getRequestUrl.mockReturnValue(mockUrl);

            const result = AttachmentHelper.getUrl(attachment);

            expect(getRequestUrl).toHaveBeenCalledWith(mockUrl);
            expect(result).toBe(mockUrl);
        });
    });

    describe("getFormattedSize", () => {
        it("should format size in bytes", () => {
            expect(AttachmentHelper.getFormattedSize(500)).toBe("500 B");
        });

        it("should format size in kilobytes (binary)", () => {
            expect(AttachmentHelper.getFormattedSize(1536)).toBe("1.5 KB"); // 1.5 * 1024
        });

        it("should format whole kilobytes without decimals", () => {
            expect(AttachmentHelper.getFormattedSize(1024)).toBe("1 KB");
        });

        it("should format size in megabytes (binary)", () => {
            expect(AttachmentHelper.getFormattedSize(5242880)).toBe("5 MB"); // 5 * 1024 * 1024
        });

        it("should format fractional megabytes with 1 decimal", () => {
            expect(AttachmentHelper.getFormattedSize(1572864)).toBe("1.5 MB"); // 1.5 * 1024 * 1024
        });

        it("should format whole megabytes without decimals", () => {
            expect(AttachmentHelper.getFormattedSize(10485760)).toBe("10 MB"); // 10 * 1024 * 1024
            expect(AttachmentHelper.getFormattedSize(20971520)).toBe("20 MB"); // 20 * 1024 * 1024
        });
    });

    describe("getFormattedTotalSize", () => {
        it("should calculate total size of multiple attachments", () => {
            const attachments: Attachment[] = [
                { name: "file1.txt", blobId: "1", size: 1024, state: "idle" },
                { name: "file2.txt", blobId: "2", size: 2048, state: "idle" },
            ];
            expect(AttachmentHelper.getFormattedTotalSize(attachments)).toBe("3 KB");
        });

        it("should return 0 B for empty array", () => {
            expect(AttachmentHelper.getFormattedTotalSize([])).toBe("0 B");
        });
    });
});
