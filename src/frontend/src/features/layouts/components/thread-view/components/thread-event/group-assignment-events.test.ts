import { describe, it, expect } from 'vitest';
import { groupAssignmentEvents, computeAssignmentNetChange, RenderItem } from './index';
import { ThreadEvent, ThreadEventTypeEnum, Message } from '@/features/api/gen/models';
import { TimelineItem } from '@/features/providers/mailbox';

const makeAssignEvent = (
    id: string,
    authorId: string | null,
    assignees: { id: string; name: string }[],
    type: ThreadEventTypeEnum = ThreadEventTypeEnum.assign,
    createdAt = '2026-01-01T10:00:00Z',
): ThreadEvent => ({
    id,
    thread: 'thread-1',
    type,
    channel: null,
    author: authorId
        ? ({ id: authorId, full_name: `User ${authorId}`, email: `${authorId}@example.com` } as ThreadEvent['author'])
        : (null as unknown as ThreadEvent['author']),
    data: { assignees },
    has_unread_mention: false,
    is_editable: false,
    created_at: createdAt,
    updated_at: createdAt,
});

const makeMessageItem = (id: string): TimelineItem => ({
    type: 'message',
    data: { id } as unknown as Message,
    created_at: '2026-01-01T10:00:30Z',
});

const asEventItem = (event: ThreadEvent): TimelineItem => ({
    type: 'event',
    data: event,
    created_at: event.created_at,
});

describe('groupAssignmentEvents', () => {
    it('leaves messages untouched and wraps events individually when alone', () => {
        const assign = makeAssignEvent('e1', 'alice', [{ id: 'bob', name: 'Bob' }]);
        const items: TimelineItem[] = [makeMessageItem('m1'), asEventItem(assign)];

        const result = groupAssignmentEvents(items);

        expect(result).toHaveLength(2);
        expect(result[0].kind).toBe('message');
        expect(result[1]).toEqual<RenderItem>({
            kind: 'event',
            data: assign,
            created_at: assign.created_at,
        });
    });

    it('groups 2+ consecutive assign/unassign events by the same author', () => {
        const e1 = makeAssignEvent('e1', 'alice', [{ id: 'bob', name: 'Bob' }], ThreadEventTypeEnum.assign);
        const e2 = makeAssignEvent('e2', 'alice', [{ id: 'bob', name: 'Bob' }], ThreadEventTypeEnum.unassign);
        const items: TimelineItem[] = [asEventItem(e1), asEventItem(e2)];

        const result = groupAssignmentEvents(items);

        expect(result).toHaveLength(1);
        expect(result[0].kind).toBe('assignment_group');
        if (result[0].kind !== 'assignment_group') throw new Error('type-guard');
        expect(result[0].events).toEqual([e1, e2]);
        expect(result[0].created_at).toBe(e2.created_at);
    });

    it('does not group events from different authors', () => {
        const e1 = makeAssignEvent('e1', 'alice', [{ id: 'bob', name: 'Bob' }]);
        const e2 = makeAssignEvent('e2', 'charlie', [{ id: 'dave', name: 'Dave' }]);
        const items: TimelineItem[] = [asEventItem(e1), asEventItem(e2)];

        const result = groupAssignmentEvents(items);

        expect(result).toHaveLength(2);
        expect(result.every((r) => r.kind === 'event')).toBe(true);
    });

    it('breaks grouping when an unrelated item (e.g. message) sits between events', () => {
        const e1 = makeAssignEvent('e1', 'alice', [{ id: 'bob', name: 'Bob' }]);
        const e2 = makeAssignEvent('e2', 'alice', [{ id: 'bob', name: 'Bob' }], ThreadEventTypeEnum.unassign);
        const items: TimelineItem[] = [asEventItem(e1), makeMessageItem('m1'), asEventItem(e2)];

        const result = groupAssignmentEvents(items);

        expect(result.map((r) => r.kind)).toEqual(['event', 'message', 'event']);
    });

    it('groups 3+ events from the same author in a single bucket', () => {
        const e1 = makeAssignEvent('e1', 'alice', [{ id: 'bob', name: 'Bob' }]);
        const e2 = makeAssignEvent('e2', 'alice', [{ id: 'bob', name: 'Bob' }], ThreadEventTypeEnum.unassign);
        const e3 = makeAssignEvent('e3', 'alice', [{ id: 'charlie', name: 'Charlie' }]);
        const items: TimelineItem[] = [asEventItem(e1), asEventItem(e2), asEventItem(e3)];

        const result = groupAssignmentEvents(items);

        expect(result).toHaveLength(1);
        if (result[0].kind !== 'assignment_group') throw new Error('type-guard');
        expect(result[0].events).toHaveLength(3);
    });
});

describe('computeAssignmentNetChange', () => {
    it('returns a single add for a lone assign', () => {
        const e1 = makeAssignEvent('e1', 'alice', [{ id: 'bob', name: 'Bob' }]);
        expect(computeAssignmentNetChange([e1])).toEqual([
            { id: 'bob', name: 'Bob', status: 'added' },
        ]);
    });

    it('cancels out an assign followed by an unassign for the same user', () => {
        const e1 = makeAssignEvent('e1', 'alice', [{ id: 'bob', name: 'Bob' }], ThreadEventTypeEnum.assign);
        const e2 = makeAssignEvent('e2', 'alice', [{ id: 'bob', name: 'Bob' }], ThreadEventTypeEnum.unassign);
        expect(computeAssignmentNetChange([e1, e2])).toEqual([]);
    });

    it('returns mixed added/removed for distinct users', () => {
        const e1 = makeAssignEvent('e1', 'alice', [{ id: 'bob', name: 'Bob' }], ThreadEventTypeEnum.assign);
        const e2 = makeAssignEvent('e2', 'alice', [{ id: 'carol', name: 'Carol' }], ThreadEventTypeEnum.unassign);
        const result = computeAssignmentNetChange([e1, e2]);
        expect(result).toHaveLength(2);
        expect(result).toContainEqual({ id: 'bob', name: 'Bob', status: 'added' });
        expect(result).toContainEqual({ id: 'carol', name: 'Carol', status: 'removed' });
    });

    it('keeps only the latest status when the same user is touched multiple times in the same direction', () => {
        const e1 = makeAssignEvent('e1', 'alice', [{ id: 'bob', name: 'Bob' }], ThreadEventTypeEnum.assign);
        const e2 = makeAssignEvent('e2', 'alice', [{ id: 'bob', name: 'Bob' }], ThreadEventTypeEnum.assign);
        expect(computeAssignmentNetChange([e1, e2])).toEqual([
            { id: 'bob', name: 'Bob', status: 'added' },
        ]);
    });
});
