import React, { useCallback, useEffect, useRef, useState } from "react";
import { TextHelper } from "@/features/utils/text-helper";
import { DateHelper } from "@/features/utils/date-helper";
import { Message, ThreadEvent as ThreadEventType, ThreadEventTypeEnum, ThreadEventAssigneesData, ThreadEventIMData } from "@/features/api/gen/models";
import { useThreadsEventsDestroy } from "@/features/api/gen/thread-events/thread-events";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/features/auth";
import { useMailboxContext, TimelineItem } from "@/features/providers/mailbox";
import { Badge } from "@/features/ui/components/badge";
import { AVATAR_COLORS, Icon, IconSize, IconType, UserAvatar } from "@gouvfr-lasuite/ui-kit";
import { Button, useModals } from "@gouvfr-lasuite/cunningham-react";
import clsx from "clsx";

const TWO_MINUTES_MS = 2 * 60 * 1000;

type TypedThreadEvent<T extends ThreadEventTypeEnum> = ThreadEventType & {
  type: T,
  data: T extends 'im' ? ThreadEventIMData
  : T extends 'assign' ? ThreadEventAssigneesData
  : T extends 'unassign' ? ThreadEventAssigneesData
  : unknown
};

const isAssignmentEvent = (event: ThreadEventType): event is TypedThreadEvent<'assign' | 'unassign'> =>
    event.type === ThreadEventTypeEnum.assign || event.type === ThreadEventTypeEnum.unassign;

const isIMEvent = (event: ThreadEventType): event is TypedThreadEvent<'im'> =>
    event.type === ThreadEventTypeEnum.im;

/**
 * Rendered timeline item used by the thread view.
 *
 * Adds an ``assignment_group`` variant on top of ``TimelineItem`` that wraps
 * consecutive ASSIGN/UNASSIGN events by the same author so the UI can collapse
 * them into a single summary line, mirroring — at a longer timescale — the
 * idea behind the backend "undo window".
 */
export type RenderItem =
    | { kind: 'message'; data: Message; created_at: string }
    | { kind: 'event'; data: ThreadEventType; created_at: string }
    | { kind: 'assignment_group'; events: ThreadEventType[]; created_at: string };

export type AssignmentNetChange = { id: string; name: string; status: 'added' | 'removed' };

/**
 * Collapses runs of 2+ consecutive ASSIGN/UNASSIGN events from the same author
 * (no other item between them) into a single ``assignment_group`` render item.
 *
 * Solo events are left untouched so the existing single-event rendering still
 * kicks in. The backend undo window already absorbs most fast click-regrets;
 * this handles the "changed my mind several minutes later" case that ends up
 * producing multiple events the backend can no longer merge.
 */
export const groupAssignmentEvents = (items: readonly TimelineItem[]): RenderItem[] => {
    const result: RenderItem[] = [];
    let buffer: ThreadEventType[] = [];

    const flushBuffer = () => {
        if (buffer.length === 0) return;
        if (buffer.length === 1) {
            const single = buffer[0];
            result.push({ kind: 'event', data: single, created_at: single.created_at });
        } else {
            const last = buffer[buffer.length - 1];
            result.push({ kind: 'assignment_group', events: [...buffer], created_at: last.created_at });
        }
        buffer = [];
    };

    for (const item of items) {
        if (item.type === 'event' && isAssignmentEvent(item.data)) {
            const currentAuthorId = item.data.author?.id ?? null;
            const bufferAuthorId = buffer[0]?.author?.id ?? null;
            if (buffer.length > 0 && currentAuthorId !== bufferAuthorId) {
                flushBuffer();
            }
            buffer.push(item.data);
            continue;
        }
        flushBuffer();
        if (item.type === 'event') {
            result.push({ kind: 'event', data: item.data, created_at: item.created_at });
        } else {
            result.push({ kind: 'message', data: item.data, created_at: item.created_at });
        }
    }
    flushBuffer();
    return result;
};

/**
 * Reduces a series of ASSIGN/UNASSIGN events into the net set of changes.
 *
 * A user assigned then unassigned (or vice versa) inside the same group ends
 * up cancelled out, mirroring the net user-visible effect of the run.
 */
export const computeAssignmentNetChange = (events: ThreadEventType[]): AssignmentNetChange[] => {
    const net = new Map<string, AssignmentNetChange | null>();
    for (const event of events) {
        const data = event.data as ThreadEventAssigneesData | null;
        const assignees = data?.assignees ?? [];
        const incoming: 'added' | 'removed' =
            event.type === ThreadEventTypeEnum.assign ? 'added' : 'removed';
        for (const assignee of assignees) {
            const existing = net.get(assignee.id);
            if (existing && existing.status !== incoming) {
                net.set(assignee.id, null);
            } else {
                net.set(assignee.id, { id: assignee.id, name: assignee.name, status: incoming });
            }
        }
    }
    return Array.from(net.values()).filter((v): v is AssignmentNetChange => v !== null);
};

/**
 * Computes the avatar palette color for a given name.
 * Mirrors the hash logic used by UserAvatar from @gouvfr-lasuite/ui-kit.
 */
const getAvatarColor = (name: string): string => {
    let hash = 0;
    for (let i = 0; i < name.length; i++) {
        hash += name.charCodeAt(i);
    }
    return AVATAR_COLORS[hash % AVATAR_COLORS.length];
};

type ThreadEventProps = {
    event: ThreadEventType;
    isCondensed?: boolean;
    onEdit?: (event: ThreadEventType) => void;
    onDelete?: (eventId: string) => void;
    /**
     * Ref setter wired by the parent when the event carries an unread mention,
     * used by the IntersectionObserver that marks mentions as read on scroll.
     * Receives the bubble element — the observer needs a target with a real
     * bounding box to reliably report intersections.
     */
    mentionRef?: (el: HTMLDivElement | null) => void;
    /**
     * True when this event OR any subsequent event condensed with it carries
     * an unread mention for the current user. Drives the badge shown in the
     * header. Computed by the parent so the first event of a condensed group
     * surfaces mentions that would otherwise be hidden on condensed siblings.
     */
    hasUnreadMention?: boolean;
};

/**
 * Returns true if this IM event should show a condensed view (no header),
 * because the previous event is also an IM from the same author within 2 minutes.
 */
export const isCondensed = (event: ThreadEventType, previousEvent?: ThreadEventType | null): boolean => {
    if (!previousEvent) return false;
    if (event.type !== ThreadEventTypeEnum.im || previousEvent.type !== ThreadEventTypeEnum.im) return false;
    if (event.author?.id !== previousEvent.author?.id) return false;
    const diff = new Date(event.created_at).getTime() - new Date(previousEvent.created_at).getTime();
    return Math.abs(diff) < TWO_MINUTES_MS;
};

/**
 * Renders a thread event in the timeline.
 * For type=im: renders as a chat bubble with avatar, author name, and content.
 * Consecutive IMs from the same author within 2 minutes are condensed (no header).
 * For other types: renders a minimal card with type badge and data.
 */
export const ThreadEvent = ({ event, isCondensed = false, onEdit, onDelete, mentionRef, hasUnreadMention = false }: ThreadEventProps) => {
    const { t, i18n } = useTranslation();
    const { user } = useAuth();
    const modals = useModals();
    const { invalidateThreadEvents } = useMailboxContext();
    const isAuthor = event.author?.id === user?.id;
    const isEdited = Math.abs(new Date(event.updated_at).getTime() - new Date(event.created_at).getTime()) > 1000;
    // Edit/delete actions are only available to the author while the
    // server-side edit delay has not elapsed (MAX_THREAD_EVENT_EDIT_DELAY).
    const canModify = isAuthor && event.is_editable;

    const deleteEvent = useThreadsEventsDestroy();
    const [showActions, setShowActions] = useState(false);
    const longPressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const bubbleRef = useRef<HTMLDivElement>(null);

    const [pressing, setPressing] = useState(false);

    const handleTouchStart = useCallback(() => {
        setPressing(true);
        longPressTimer.current = setTimeout(() => {
            setPressing(false);
            setShowActions(true);
            navigator.vibrate?.(50);
        }, 500);
    }, []);

    const cancelLongPress = useCallback(() => {
        setPressing(false);
        if (longPressTimer.current) {
            clearTimeout(longPressTimer.current);
            longPressTimer.current = null;
        }
    }, []);

    useEffect(() => {
        if (!showActions) return;
        const handleClickOutside = (e: MouseEvent | TouchEvent) => {
            if (bubbleRef.current && !bubbleRef.current.contains(e.target as Node)) {
                setShowActions(false);
            }
        };
        document.addEventListener("mousedown", handleClickOutside);
        document.addEventListener("touchstart", handleClickOutside);
        return () => {
            document.removeEventListener("mousedown", handleClickOutside);
            document.removeEventListener("touchstart", handleClickOutside);
        };
    }, [showActions]);

    const handleDelete = async () => {
        const decision = await modals.deleteConfirmationModal({
            title: <span className="c__modal__text--centered">{t('Delete internal comment')}</span>,
            children: t('Are you sure you want to delete this internal comment? It will be deleted for all users. This action cannot be undone.'),
        });
        if (decision !== 'delete') return;
        deleteEvent.mutate(
            { threadId: event.thread, id: event.id },
            { onSuccess: () => {
                onDelete?.(event.id);
                invalidateThreadEvents();
            } },
        );
    };

    if (isIMEvent(event)) {
        const authorName = event.author?.full_name || event.author?.email || "";
        const avatarColor = getAvatarColor(authorName);
        const isMentioned = user
            ? event.data?.mentions?.map((m) => m.id)?.includes(user.id)
            : false;
        const content = event.data?.content ?? "";

        const imClasses = clsx(
            "thread-event",
            "thread-event--im",
            {
                "thread-event--condensed": isCondensed,
            },
        );

        const bubbleStyle = {
            "--thread-event-color": `var(--c--contextuals--background--palette--${avatarColor}--primary)`,
        } as React.CSSProperties;

        return (
            <div className={imClasses} id={`thread-event-${event.id}`}>
                <div
                    ref={(el) => {
                        // Combined ref: keeps the local bubbleRef (used for
                        // click-outside detection) and the parent-provided
                        // mentionRef (used by the IntersectionObserver that
                        // acknowledges unread mentions on scroll) in sync.
                        bubbleRef.current = el;
                        mentionRef?.(el);
                    }}
                    className={`thread-event__bubble${showActions ? " thread-event__bubble--actions-visible" : ""}`}
                    style={bubbleStyle}
                    data-event-id={event.id}
                >
                    {!isCondensed && (
                        <div className="thread-event__header">
                            <span className="thread-event__author">
                                <UserAvatar fullName={event.author?.full_name || event.author?.email || t("Unknown")} size="xsmall" />
                                {event.author?.full_name || event.author?.email || t("Unknown")}
                            </span>
                            <span className="thread-event__time">
                                {t('{{date}} at {{time}}', {
                                    date: DateHelper.formatDate(event.created_at, i18n.resolvedLanguage, false),
                                    time: new Date(event.created_at).toLocaleString(i18n.resolvedLanguage, {
                                        minute: '2-digit',
                                        hour: '2-digit',
                                    }),
                                })}
                            </span>
                            {hasUnreadMention && (
                                <Badge
                                    color="warning"
                                    variant="secondary"
                                    compact
                                    role="status"
                                    className="thread-event__mention-badge"
                                >
                                    <Icon
                                        type={IconType.OUTLINED}
                                        size={IconSize.X_SMALL}
                                        name="alternate_email"
                                        aria-hidden="true"
                                    />
                                    {t('Unread mention')}
                                </Badge>
                            )}
                        </div>
                    )}
                    <div
                        className={`thread-event__content${pressing ? " thread-event__content--pressing" : ""}`}
                        onTouchStart={canModify ? handleTouchStart : undefined}
                        onTouchEnd={canModify ? cancelLongPress : undefined}
                        onTouchMove={canModify ? cancelLongPress : undefined}
                        onTouchCancel={canModify ? cancelLongPress : undefined}
                    >
                        {TextHelper.renderLinks(
                          TextHelper.renderMentions(
                              content,
                              isMentioned ? user?.full_name ?? undefined : undefined,
                              { baseClassName: "thread-event" }
                          )
                        )}
                        {isEdited && (
                            <span className="thread-event__edited-badge">({t("edited")})</span>
                        )}
                    </div>
                    {canModify && (
                        <div className="thread-event__actions">
                            <Button
                                size="nano"
                                variant="tertiary"
                                color="brand"
                                icon={<Icon type={IconType.OUTLINED} name="edit" aria-hidden="true" />}
                                aria-label={t("Edit")}
                                title={t("Edit")}
                                onClick={() => {
                                    setShowActions(false);
                                    onEdit?.(event);
                                }}
                            />
                            <Button
                                size="nano"
                                variant="tertiary"
                                color="brand"
                                icon={<Icon type={IconType.OUTLINED} name="delete" aria-hidden="true" />}
                                aria-label={t("Delete")}
                                title={t("Delete")}
                                onClick={() => {
                                    setShowActions(false);
                                    handleDelete();
                                }}
                            />
                        </div>
                    )}
                </div>
            </div>
        );
    }

    // Assignment events: system-style compact rendering
    if (isAssignmentEvent(event)) {
        const isAssign = event.type === ThreadEventTypeEnum.assign;
        const assigneeData = event.data;
        const assigneeNames = assigneeData.assignees?.map((a) => a.name).join(", ") ?? "";
        const assigneeCount = assigneeData.assignees?.length ?? 0;
        // UNASSIGN events with a null author are system events emitted when a
        // user loses full edit rights on the thread. Drop the author prefix so
        // the timeline does not read "Unknown unassigned X". Staying generic
        // ("was unassigned") on purpose: any more specific wording belongs on
        // a dedicated ThreadEvent type, not on this branch.
        const isSystemUnassign = !isAssign && event.author === null;
        const authorName = event.author?.full_name || event.author?.email || t("Unknown");
        let message: string;
        if (isSystemUnassign) {
            message = t("{{assignees}} was unassigned", {
                assignees: assigneeNames,
                count: assigneeCount,
            });
        } else if (isAssign) {
            message = t("{{author}} assigned {{assignees}}", {
                author: authorName,
                assignees: assigneeNames,
                count: assigneeCount,
            });
        } else {
            message = t("{{author}} unassigned {{assignees}}", {
                author: authorName,
                assignees: assigneeNames,
                count: assigneeCount,
            });
        }
        return (
            <div className="thread-event thread-event--system">
                <Icon name={isAssign ? "person_add" : "person_remove"} type={IconType.OUTLINED} aria-hidden="true" />
                <span className="thread-event__system-text">{message}</span>
                <span className="thread-event__system-time">
                    {t('{{date}} at {{time}}', {
                        date: DateHelper.formatDate(event.created_at, i18n.resolvedLanguage, false),
                        time: new Date(event.created_at).toLocaleString(i18n.resolvedLanguage, {
                            minute: '2-digit',
                            hour: '2-digit',
                        }),
                    })}
                </span>
            </div>
        );
    }

    // Fallback for other event types
    return (
        <div className="thread-event thread-event--generic">
            <div className="thread-event__badge">{event.type}</div>
            <div className="thread-event__body">
                <div className="thread-event__header">
                    <span className="thread-event__time">
                        {t('{{date}} at {{time}}', {
                            date: DateHelper.formatDate(event.created_at, i18n.resolvedLanguage, false),
                            time: new Date(event.created_at).toLocaleString(i18n.resolvedLanguage, {
                                minute: '2-digit',
                                hour: '2-digit',
                            }),
                        })}
                        {isEdited && ` · ${t('Modified')}`}
                    </span>
                </div>
                {(event?.data as { content?: string })?.content && (
            <div className="thread-event__content">{(event?.data as { content?: string })?.content}</div>
                )}
            </div>
        </div>
    );
};

type GroupedAssignmentEventProps = {
    events: ThreadEventType[];
};

/**
 * Renders a run of consecutive ASSIGN/UNASSIGN events by the same author as a
 * single system-style line. Shows the *net* change (assignees added and/or
 * removed across the whole run) so bouncing between assign states collapses to
 * its actual outcome. When the net cancels out entirely, falls back to a
 * neutral "adjusted assignments" wording that still records that something
 * happened without listing phantom users.
 */
export const GroupedAssignmentEvent = ({ events }: GroupedAssignmentEventProps) => {
    const { t, i18n } = useTranslation();
    const last = events[events.length - 1];
    const authorName = last.author?.full_name || last.author?.email || t("Unknown");
    const net = computeAssignmentNetChange(events);
    const isEmptyNet = net.length === 0;

    const message = isEmptyNet
        ? t("{{author}} adjusted assignments", { author: authorName })
        : t("{{author}} modified assignments", { author: authorName });

    return (
        <div className="thread-event thread-event--system thread-event--assignment-group">
            <Icon name="manage_accounts" type={IconType.OUTLINED} aria-hidden="true" />
            <span className="thread-event__system-text">
                {message}
                {!isEmptyNet && (
                    <span className="thread-event__assignment-changes">
                        {net.map((change) => (
                            <span
                                key={change.id}
                                className={clsx(
                                    "thread-event__assignment-change",
                                    change.status === 'added'
                                        ? "thread-event__assignment-change--added"
                                        : "thread-event__assignment-change--removed",
                                )}
                            >
                                {change.status === 'added' ? '+' : '−'} {change.name}
                            </span>
                        ))}
                    </span>
                )}
            </span>
            <span className="thread-event__system-time">
                {t('{{date}} at {{time}}', {
                    date: DateHelper.formatDate(last.created_at, i18n.resolvedLanguage, false),
                    time: new Date(last.created_at).toLocaleString(i18n.resolvedLanguage, {
                        minute: '2-digit',
                        hour: '2-digit',
                    }),
                })}
            </span>
        </div>
    );
};
