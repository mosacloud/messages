import { defaultBlockSpecs } from '@blocknote/core';

export const ALLOWED_IMAGE_MIME_TYPES = [
    'image/jpeg',
    'image/png',
    'image/gif',
    'image/webp',
];

// Override the default image block to:
// - Restrict accepted MIME types (affects file picker and drag & drop routing)

export const imageBlockSpec: typeof defaultBlockSpecs.image = {
    ...defaultBlockSpecs.image,
    implementation: {
        ...defaultBlockSpecs.image.implementation,
        meta: {
            ...defaultBlockSpecs.image.implementation.meta,
            fileBlockAccept: ALLOWED_IMAGE_MIME_TYPES,
        },
    },
};
