import { useState, useMemo, useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { Icon, IconType, Spinner } from "@gouvfr-lasuite/ui-kit";
import {
    convertIcsCalendar,
    IcsCalendar,
    IcsEvent,
    IcsAttendee,
} from "ts-ics";
import { Attachment } from "@/features/api/gen/models";
import { StatusEnum } from "@/features/api/gen";
import { AttachmentHelper } from "@/features/utils/attachment-helper";
import { ContactChip } from "@/features/ui/components/contact-chip";
import { Badge } from "@/features/ui/components/badge";
import { addToast, ToasterItem } from "@/features/ui/components/toaster";
import { fetchAPI } from "@/features/api/fetch-api";
import { useTaskStatus } from "@/hooks/use-task-status";
import {
    getEventEnd,
    TextHelper,
    formatEventDateRange,
    formatRecurrenceRule,
    getAttendeeStatusInfo,
    createContactFromAttendee,
} from "./calendar-helper";

type CalendarInviteProps = {
    attachment: Attachment;
    canDownload?: boolean;
    mailboxId?: string;
};

type CalendarInfo = {
    id: string;
    name: string;
};

type ConflictInfo = {
    summary: string;
    start: string | null;
    end: string | null;
    calendar_name: string;
};

type RsvpResponse = "ACCEPTED" | "DECLINED" | "TENTATIVE";

const MAX_VISIBLE_ATTENDEES = 3;
const MAX_DESCRIPTION_LENGTH = 200;

/**
 * Extracted download button to avoid duplication
 */
const DownloadButton = ({
    downloadUrl,
    name,
    variant = "secondary",
}: {
    downloadUrl: string;
    name: string;
    variant?: "primary" | "secondary" | "tertiary";
}) => {
    const { t } = useTranslation();
    return (
        <Button
            size="small"
            variant={variant}
            icon={<Icon name="download" type={IconType.OUTLINED} />}
            href={downloadUrl}
            download={name.startsWith("unnamed") ? "invitation.ics" : name}
        >
            {t("Download invitation")}
        </Button>
    );
};

/**
 * Conflict detection display
 */
const ConflictWarning = ({ conflicts, language }: { conflicts: ConflictInfo[]; language: string }) => {
    const { t } = useTranslation();
    if (conflicts.length === 0) return null;

    return (
        <div className="calendar-invite__conflicts" role="alert">
            <div className="calendar-invite__conflicts-header">
                <Icon name="warning" type={IconType.OUTLINED} />
                <span>
                    {t("{{count}} conflicting events", { count: conflicts.length })}
                </span>
            </div>
            <ul className="calendar-invite__conflicts-list">
                {conflicts.map((conflict, idx) => (
                    <li key={idx} className="calendar-invite__conflict-item">
                        <span className="calendar-invite__conflict-summary">
                            {conflict.summary}
                        </span>
                        <span className="calendar-invite__conflict-calendar">
                            {conflict.calendar_name}
                        </span>
                        {conflict.start && (
                            <span className="calendar-invite__conflict-time">
                                {new Date(conflict.start).toLocaleString(language)}
                            </span>
                        )}
                    </li>
                ))}
            </ul>
        </div>
    );
};

/**
 * Calendar chooser dropdown
 */
const CalendarChooser = ({
    calendars,
    selectedCalendarId,
    onSelect,
}: {
    calendars: CalendarInfo[];
    selectedCalendarId: string | null;
    onSelect: (id: string | null) => void;
}) => {
    const { t } = useTranslation();
    if (calendars.length <= 1) return null;

    return (
        <div className="calendar-invite__calendar-chooser">
            <Icon name="event_note" type={IconType.OUTLINED} className="calendar-invite__detail-icon" />
            <select
                className="calendar-invite__calendar-select"
                value={selectedCalendarId ?? ""}
                onChange={(e) => onSelect(e.target.value || null)}
                aria-label={t("Choose calendar")}
            >
                {calendars.map((cal) => (
                    <option key={cal.id} value={cal.id}>
                        {cal.name}
                    </option>
                ))}
            </select>
        </div>
    );
};

/**
 * RSVP action buttons
 */
const RsvpButtons = ({
    onRespond,
    isPending,
    currentResponse,
    isCancellation,
}: {
    onRespond: (response: RsvpResponse) => void;
    isPending: boolean;
    currentResponse: RsvpResponse | null;
    isCancellation: boolean;
}) => {
    const { t } = useTranslation();

    if (isCancellation) return null;

    const buttons: { response: RsvpResponse; label: string; icon: string; variant: "primary" | "secondary" | "tertiary" }[] = [
        { response: "ACCEPTED", label: t("Accept"), icon: "check_circle", variant: currentResponse === "ACCEPTED" ? "primary" : "secondary" },
        { response: "TENTATIVE", label: t("Maybe"), icon: "help", variant: currentResponse === "TENTATIVE" ? "primary" : "secondary" },
        { response: "DECLINED", label: t("Decline"), icon: "cancel", variant: currentResponse === "DECLINED" ? "primary" : "secondary" },
    ];

    return (
        <div className="calendar-invite__rsvp-buttons">
            {buttons.map(({ response, label, icon, variant }) => (
                <Button
                    key={response}
                    size="small"
                    variant={variant}
                    icon={
                        isPending ? (
                            <Spinner size="sm" />
                        ) : (
                            <Icon name={icon} type={IconType.OUTLINED} />
                        )
                    }
                    onClick={() => onRespond(response)}
                    disabled={isPending}
                >
                    {label}
                </Button>
            ))}
        </div>
    );
};

/**
 * Renders a single event's details with its own state for attendees/description
 */
const EventCard = ({
    event,
    language,
    conflicts,
}: {
    event: IcsEvent;
    language: string;
    conflicts: ConflictInfo[];
}) => {
    const { t } = useTranslation();
    const [showAllAttendees, setShowAllAttendees] = useState(false);
    const [showFullDescription, setShowFullDescription] = useState(false);

    const eventStart = event.start?.date;
    const eventEnd = getEventEnd(event);
    const attendeeCount = event.attendees?.length ?? 0;
    const hasAttendees = attendeeCount > 0;
    const descriptionTruncated =
        !!event.description &&
        event.description.length > MAX_DESCRIPTION_LENGTH;

    const { visibleAttendees, hiddenCount } = useMemo(() => {
        if (!event.attendees) {
            return { visibleAttendees: [] as IcsAttendee[], hiddenCount: 0 };
        }

        const total = event.attendees.length;
        if (showAllAttendees || total <= MAX_VISIBLE_ATTENDEES) {
            return { visibleAttendees: event.attendees, hiddenCount: 0 };
        }

        return {
            visibleAttendees: event.attendees.slice(0, MAX_VISIBLE_ATTENDEES),
            hiddenCount: total - MAX_VISIBLE_ATTENDEES,
        };
    }, [event.attendees, showAllAttendees]);

    const displayedDescription = useMemo(() => {
        if (!event.description) return null;
        if (showFullDescription || !descriptionTruncated) {
            return event.description;
        }
        return event.description.slice(0, MAX_DESCRIPTION_LENGTH) + "\u2026";
    }, [event.description, showFullDescription]);

    return (
        <div className="calendar-invite__event">
            <header className="calendar-invite__header">
                <div className="calendar-invite__icon">
                    <Icon name="event" type={IconType.OUTLINED} />
                </div>
                <div className="calendar-invite__title-section">
                    <h3 className="calendar-invite__title">{event.summary}</h3>
                    {event.status && (
                        <Badge
                            className={`calendar-invite__event-status calendar-invite__event-status--${event.status.toLowerCase()}`}
                        >
                            {t(`event.status.${event.status.toLowerCase()}`)}
                        </Badge>
                    )}
                </div>
            </header>

            <div className="calendar-invite__details">
                {/* Date and Time */}
                {eventStart && (
                    <div className="calendar-invite__detail-row">
                        <Icon
                            name="schedule"
                            type={IconType.OUTLINED}
                            className="calendar-invite__detail-icon"
                        />
                        <span>
                            {formatEventDateRange(
                                eventStart,
                                eventEnd,
                                language,
                            )}
                        </span>
                    </div>
                )}

                {/* Recurrence */}
                {event.recurrenceRule && (
                    <div className="calendar-invite__detail-row">
                        <Icon
                            name="repeat"
                            type={IconType.OUTLINED}
                            className="calendar-invite__detail-icon"
                        />
                        <span>
                            {formatRecurrenceRule(
                                event.recurrenceRule,
                                t,
                                language,
                            )}
                        </span>
                    </div>
                )}

                {/* Location */}
                {event.location && (
                    <div className="calendar-invite__detail-row">
                        <Icon
                            name="location_on"
                            type={IconType.OUTLINED}
                            className="calendar-invite__detail-icon"
                        />
                        <span>
                            {TextHelper.renderLinks(
                                [event.location],
                                { props: { className: "calendar-invite__link" } }
                            )}
                        </span>
                    </div>
                )}

                {/* Organizer */}
                {event.organizer && (
                    <div className="calendar-invite__detail-row">
                        <Icon
                            name="person"
                            type={IconType.OUTLINED}
                            className="calendar-invite__detail-icon"
                        />
                        <ContactChip
                            contact={createContactFromAttendee(
                                event.organizer,
                            )}
                            displayEmail
                        />
                    </div>
                )}

                {/* Description */}
                {displayedDescription && (
                    <div className="calendar-invite__description">
                        <Icon
                            name="notes"
                            type={IconType.OUTLINED}
                            className="calendar-invite__detail-icon"
                        />
                        <div>
                            <p>{TextHelper.renderLinks([displayedDescription])}</p>
                            {descriptionTruncated && (
                                <button
                                    type="button"
                                    className="calendar-invite__show-more"
                                    onClick={() =>
                                        setShowFullDescription(
                                            !showFullDescription,
                                        )
                                    }
                                    aria-expanded={showFullDescription}
                                >
                                    {showFullDescription
                                        ? t("Show less")
                                        : t("Show more")}
                                </button>
                            )}
                        </div>
                    </div>
                )}

                {/* Conflict Warning */}
                {conflicts.length > 0 && (
                    <ConflictWarning conflicts={conflicts} language={language} />
                )}

                {/* Attendees */}
                {hasAttendees && (
                    <div className="calendar-invite__attendees">
                        <div className="calendar-invite__attendees-header">
                            <Icon
                                name="group"
                                type={IconType.OUTLINED}
                                className="calendar-invite__detail-icon"
                            />
                            <span>
                                {t("{{count}} attendees", {
                                    count: attendeeCount,
                                })}
                            </span>
                        </div>
                        <ul className="calendar-invite__attendee-list">
                            {visibleAttendees.map((attendee) => {
                                const statusInfo = getAttendeeStatusInfo(
                                    attendee.partstat,
                                    t,
                                );
                                return (
                                    <li
                                        key={attendee.email}
                                        className="calendar-invite__attendee"
                                    >
                                        <ContactChip
                                            contact={createContactFromAttendee(
                                                attendee,
                                            )}
                                        />
                                        <span
                                            className={`calendar-invite__attendee-status ${statusInfo.className}`}
                                            title={statusInfo.label}
                                        >
                                            <Icon
                                                name={statusInfo.icon}
                                                type={IconType.OUTLINED}
                                            />
                                            <span>{statusInfo.label}</span>
                                        </span>
                                    </li>
                                );
                            })}
                        </ul>
                        {attendeeCount > MAX_VISIBLE_ATTENDEES && (
                            <button
                                type="button"
                                className="calendar-invite__show-more"
                                onClick={() =>
                                    setShowAllAttendees(!showAllAttendees)
                                }
                                aria-expanded={showAllAttendees}
                            >
                                {showAllAttendees
                                    ? t("Show less")
                                    : t("Show {{count}} more", {
                                          count: hiddenCount,
                                      })}
                            </button>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};

const fetchAndParseCalendar = async (url: string): Promise<IcsCalendar> => {
    const response = await fetch(url, { credentials: "include" });
    if (!response.ok) {
        throw new Error(`HTTP error: ${response.status}`);
    }
    const icsContent = await response.text();
    return convertIcsCalendar(undefined, icsContent);
};

const fetchIcsContent = async (url: string): Promise<string> => {
    const response = await fetch(url, { credentials: "include" });
    if (!response.ok) {
        throw new Error(`HTTP error: ${response.status}`);
    }
    return response.text();
};

type CalendarsApiResponse = {
    data: { calendars: CalendarInfo[] };
    status: number;
};

type ConflictsApiResponse = {
    data: { conflicts: ConflictInfo[] };
    status: number;
};

type RsvpApiResponse = {
    data: { task_id: string };
    status: number;
};

export const CalendarInvite = ({
    attachment,
    canDownload = true,
    mailboxId,
}: CalendarInviteProps) => {
    const { t, i18n } = useTranslation();
    const [selectedCalendarId, setSelectedCalendarId] = useState<string | null>(null);
    const [rsvpResponse, setRsvpResponse] = useState<RsvpResponse | null>(null);

    const downloadUrl = AttachmentHelper.getDownloadUrl(attachment);
    const language = i18n.resolvedLanguage || "en";

    // Fetch and parse calendar data
    const { data: calendar, isLoading, isError, refetch } = useQuery<IcsCalendar>({
        queryKey: ["calendar-invite", downloadUrl],
        queryFn: () => fetchAndParseCalendar(downloadUrl),
        meta: { noGlobalError: true },
    });

    // Fetch raw ICS content (for sending to backend)
    const { data: icsContent } = useQuery<string>({
        queryKey: ["calendar-invite-raw", downloadUrl],
        queryFn: () => fetchIcsContent(downloadUrl),
        enabled: !!mailboxId,
        meta: { noGlobalError: true },
    });

    // Fetch available calendars
    const { data: calendarsResponse } = useQuery<CalendarsApiResponse>({
        queryKey: ["calendar-calendars", mailboxId],
        queryFn: () =>
            fetchAPI<CalendarsApiResponse>(
                `/api/v1.0/mailboxes/${mailboxId}/calendar/calendars/`,
            ),
        enabled: !!mailboxId,
        meta: { noGlobalError: true },
    });

    const calendars = calendarsResponse?.data?.calendars ?? [];
    const hasCalDAV = calendars.length > 0;

    // Set default calendar when calendars load
    const effectiveCalendarId = selectedCalendarId ?? (calendars.length > 0 ? calendars[0].id : null);

    const events = calendar?.events ?? [];
    const isCancellation = calendar?.method === "CANCEL";

    // Conflict detection for the first event
    const firstEvent = events[0];
    const eventStart = firstEvent?.start?.date;
    const eventEnd = getEventEnd(firstEvent);

    const { data: conflictsResponse } = useQuery<ConflictsApiResponse>({
        queryKey: [
            "calendar-conflicts",
            mailboxId,
            eventStart?.toISOString(),
            eventEnd?.toISOString(),
        ],
        queryFn: () =>
            fetchAPI<ConflictsApiResponse>(
                `/api/v1.0/mailboxes/${mailboxId}/calendar/conflicts/`,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        start: eventStart!.toISOString(),
                        end: eventEnd!.toISOString(),
                    }),
                },
            ),
        enabled: !!mailboxId && hasCalDAV && !!eventStart && !!eventEnd,
        meta: { noGlobalError: true },
    });

    const conflicts = conflictsResponse?.data?.conflicts ?? [];

    // Task polling for RSVP/add-to-calendar (shared with import code)
    const [taskId, setTaskId] = useState<string | null>(null);
    const taskStatus = useTaskStatus(taskId);
    const isPending = !!taskId && taskStatus?.state !== StatusEnum.SUCCESS && taskStatus?.state !== StatusEnum.FAILURE;

    useEffect(() => {
        if (!taskStatus) return;
        if (taskStatus.state === StatusEnum.SUCCESS) {
            setTaskId(null);
            addToast(
                <ToasterItem type="info">
                    <span className="material-icons">check_circle</span>
                    <span>
                        {rsvpResponse
                            ? t("Response sent successfully")
                            : t("Event added to calendar")}
                    </span>
                </ToasterItem>,
            );
        } else if (taskStatus.state === StatusEnum.FAILURE) {
            setTaskId(null);
            addToast(
                <ToasterItem type="error">
                    <span className="material-icons">error</span>
                    <span>{taskStatus.error ?? t("An unexpected error occurred.")}</span>
                </ToasterItem>,
            );
        }
    }, [taskStatus?.state, rsvpResponse, t]);

    const handleRsvp = useCallback(
        async (response: RsvpResponse) => {
            if (!mailboxId || !icsContent) return;

            try {
                const result = await fetchAPI<RsvpApiResponse>(
                    `/api/v1.0/mailboxes/${mailboxId}/calendar/rsvp/`,
                    {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            ics_data: icsContent,
                            response,
                            calendar_id: effectiveCalendarId,
                        }),
                    },
                );
                setRsvpResponse(response);
                setTaskId(result.data.task_id);
            } catch {
                addToast(
                    <ToasterItem type="error">
                        <span>{t("An unexpected error occurred.")}</span>
                    </ToasterItem>,
                );
            }
        },
        [mailboxId, icsContent, effectiveCalendarId, t],
    );

    const handleAddToCalendar = useCallback(async () => {
        if (!mailboxId || !icsContent) return;

        try {
            const result = await fetchAPI<RsvpApiResponse>(
                `/api/v1.0/mailboxes/${mailboxId}/calendar/add/`,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        ics_data: icsContent,
                        calendar_id: effectiveCalendarId,
                    }),
                },
            );
            setRsvpResponse(null);
            setTaskId(result.data.task_id);
        } catch {
            addToast(
                <ToasterItem type="error">
                    <span>{t("An unexpected error occurred.")}</span>
                </ToasterItem>,
            );
        }
    }, [mailboxId, icsContent, effectiveCalendarId, t]);

    if (isLoading) {
        return (
            <div
                className="calendar-invite calendar-invite--loading"
                role="status"
                aria-live="polite"
            >
                <Spinner />
                <span>{t("Loading calendar invite...")}</span>
            </div>
        );
    }

    if (isError || !calendar) {
        return (
            <div
                className="calendar-invite calendar-invite--error"
                role="alert"
            >
                <Icon name="error" type={IconType.OUTLINED} />
                <span>{t("Failed to load calendar invite")}</span>
                <Button
                    size="small"
                    variant="tertiary"
                    onClick={() => refetch()}
                >
                    {t("Try again")}
                </Button>
                {canDownload && (
                    <DownloadButton
                        downloadUrl={downloadUrl}
                        name={attachment.name}
                        variant="tertiary"
                    />
                )}
            </div>
        );
    }

    if (events.length === 0) {
        return (
            <div
                className="calendar-invite calendar-invite--empty"
                role="status"
            >
                <Icon name="event" type={IconType.OUTLINED} />
                <span>{t("No event found in calendar invite")}</span>
                {canDownload && (
                    <DownloadButton
                        downloadUrl={downloadUrl}
                        name={attachment.name}
                        variant="tertiary"
                    />
                )}
            </div>
        );
    }

    return (
        <article className="calendar-invite" aria-label={t("Calendar invite")}>
            {isCancellation && (
                <div
                    className="calendar-invite__method-banner calendar-invite__method-banner--cancel"
                    role="alert"
                >
                    <Icon name="event_busy" type={IconType.OUTLINED} />
                    <span>{t("This event has been cancelled")}</span>
                </div>
            )}

            {events.map((event, index) => (
                <EventCard
                    key={event.uid || index}
                    event={event}
                    language={language}
                    conflicts={index === 0 ? conflicts : []}
                />
            ))}

            {/* Calendar chooser */}
            {hasCalDAV && (
                <CalendarChooser
                    calendars={calendars}
                    selectedCalendarId={effectiveCalendarId}
                    onSelect={setSelectedCalendarId}
                />
            )}

            <footer className="calendar-invite__actions">
                {/* RSVP buttons */}
                {hasCalDAV && !isCancellation && (
                    <RsvpButtons
                        onRespond={handleRsvp}
                        isPending={isPending}
                        currentResponse={rsvpResponse}
                        isCancellation={isCancellation}
                    />
                )}

                {/* Add to calendar button */}
                {hasCalDAV && !isCancellation && (
                    <Button
                        size="small"
                        variant="tertiary"
                        icon={
                            isPending ? (
                                <Spinner size="sm" />
                            ) : (
                                <Icon name="calendar_add_on" type={IconType.OUTLINED} />
                            )
                        }
                        onClick={handleAddToCalendar}
                        disabled={isPending}
                    >
                        {t("Add to calendar")}
                    </Button>
                )}

                {canDownload && (
                    <DownloadButton
                        downloadUrl={downloadUrl}
                        name={attachment.name}
                    />
                )}
            </footer>
        </article>
    );
};
